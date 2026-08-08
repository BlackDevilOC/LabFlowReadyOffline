import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

const RATE_LIMIT_WINDOW_MS = 60_000;
const RATE_LIMIT_MAX = 30;
const FAILED_LOGIN_WINDOW_MS = 15 * 60_000;
const FAILED_LOGIN_MAX = 10;

const rateByIp = new Map<string, { count: number; resetAt: number }>();
const failedByKey = new Map<string, { count: number; resetAt: number }>();

function getClientIp(req: Request): string {
  return (
    req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
    req.headers.get("cf-connecting-ip") ||
    "unknown"
  );
}

function checkRateLimit(ip: string): boolean {
  const now = Date.now();
  let entry = rateByIp.get(ip);
  if (!entry || now > entry.resetAt) {
    entry = { count: 0, resetAt: now + RATE_LIMIT_WINDOW_MS };
    rateByIp.set(ip, entry);
  }
  entry.count += 1;
  return entry.count <= RATE_LIMIT_MAX;
}

function checkFailedLogin(key: string): boolean {
  const now = Date.now();
  let entry = failedByKey.get(key);
  if (!entry || now > entry.resetAt) {
    entry = { count: 0, resetAt: now + FAILED_LOGIN_WINDOW_MS };
    failedByKey.set(key, entry);
  }
  return entry.count < FAILED_LOGIN_MAX;
}

function recordFailedLogin(key: string): void {
  const now = Date.now();
  let entry = failedByKey.get(key);
  if (!entry || now > entry.resetAt) {
    entry = { count: 0, resetAt: now + FAILED_LOGIN_WINDOW_MS };
    failedByKey.set(key, entry);
  }
  entry.count += 1;
}

function safeEqual(a: string, b: string): boolean {
  const sa = String(a ?? "");
  const sb = String(b ?? "");
  if (sa.length !== sb.length) return false;
  let out = 0;
  for (let i = 0; i < sa.length; i++) {
    out |= sa.charCodeAt(i) ^ sb.charCodeAt(i);
  }
  return out === 0;
}

function isAllowedOrigin(origin: string | null): boolean {
  if (!origin) return false;
  const extra = (Deno.env.get("PATIENT_PORTAL_ALLOWED_ORIGINS") || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  if (extra.includes("*") || extra.includes(origin)) return true;
  if (extra.some((o) => origin === o)) return true;
  try {
    const u = new URL(origin);
    if (u.hostname === "localhost" || u.hostname === "127.0.0.1") return true;
    if (u.hostname.endsWith(".github.io")) return true;
    if (u.hostname.endsWith(".duckdns.org")) return true;
  } catch {
    return false;
  }
  return extra.some((o) => origin === o);
}

function corsHeaders(origin: string | null): Record<string, string> {
  const headers: Record<string, string> = {
    "Access-Control-Allow-Headers":
      "authorization, x-client-info, apikey, content-type",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    Vary: "Origin",
  };
  if (origin && isAllowedOrigin(origin)) {
    headers["Access-Control-Allow-Origin"] = origin;
  }
  return headers;
}

function jsonResponse(
  body: Record<string, unknown>,
  status: number,
  origin: string | null,
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      ...corsHeaders(origin),
      "Content-Type": "application/json",
    },
  });
}

function sanitizeTestValues(raw: unknown): Record<string, unknown> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  let tv = raw as Record<string, unknown>;
  if (tv.test_values && typeof tv.test_values === "object") {
    tv = tv.test_values as Record<string, unknown>;
  }
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(tv)) {
    if (k !== "remarks" && k !== "test_values") out[k] = v;
  }
  return out;
}

function normalizeTestRow(row: Record<string, unknown>) {
  let tv = row.test_values;
  let remarks = row.remarks;
  if (tv && typeof tv === "object" && !Array.isArray(tv)) {
    const tvo = tv as Record<string, unknown>;
    if ((remarks === null || remarks === undefined || remarks === "") &&
      tvo.remarks) {
      remarks = tvo.remarks;
    }
    tv = sanitizeTestValues(tv);
  }
  return {
    id: row.id,
    category: row.category || "General",
    test_name: row.test_name || "Test",
    test_values: tv || {},
    remarks: String(remarks ?? "").trim(),
    created_at: row.created_at,
    status: row.status || "Pending",
  };
}

function publicPatient(p: Record<string, unknown>) {
  return {
    mr_no: p.mr_no,
    patient_name: p.patient_name,
    salutation: p.salutation,
    age: p.age,
    gender: p.gender,
    relation: p.relation,
    relation_name: p.relation_name,
    shift: p.shift,
    patient_token: p.patient_token,
  };
}

Deno.serve(async (req: Request) => {
  const origin = req.headers.get("Origin");

  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: corsHeaders(origin) });
  }

  if (req.method !== "POST") {
    return jsonResponse({ status: "error", message: "Method not allowed" }, 405, origin);
  }

  if (!isAllowedOrigin(origin)) {
    return jsonResponse({ status: "error", message: "Origin not allowed" }, 403, origin);
  }

  const ip = getClientIp(req);
  if (!checkRateLimit(ip)) {
    return jsonResponse(
      { status: "error", message: "Too many requests. Try again later." },
      429,
      origin,
    );
  }

  let body: { mr_no?: number | string; patient_token?: string; pin?: string };
  try {
    body = await req.json();
  } catch {
    return jsonResponse({ status: "error", message: "Invalid JSON body" }, 400, origin);
  }

  const pin = String(body.pin ?? "").trim();
  const mrRaw = body.mr_no;
  const token = String(body.patient_token ?? "").trim();

  if (!pin) {
    return jsonResponse(
      { status: "error", message: "PIN is required." },
      400,
      origin,
    );
  }

  const mrNo = mrRaw !== undefined && mrRaw !== null && String(mrRaw).trim() !== ""
    ? parseInt(String(mrRaw).trim(), 10)
    : null;

  if ((mrNo === null || Number.isNaN(mrNo)) && !token) {
    return jsonResponse(
      { status: "error", message: "MR number or patient token is required." },
      400,
      origin,
    );
  }

  const throttleKey = `${ip}:${mrNo ?? ""}:${token}`;
  if (!checkFailedLogin(throttleKey)) {
    return jsonResponse(
      { status: "error", message: "Too many failed attempts. Try again later." },
      429,
      origin,
    );
  }

  const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
  if (!supabaseUrl || !serviceKey) {
    return jsonResponse(
      { status: "error", message: "Server configuration error." },
      500,
      origin,
    );
  }

  const supabase = createClient(supabaseUrl, serviceKey);

  let patientQuery = supabase.from("patients").select(
    "id,mr_no,patient_name,salutation,age,gender,relation,relation_name,shift,patient_token,pwd",
  );

  if (mrNo !== null && !Number.isNaN(mrNo)) {
    patientQuery = patientQuery.eq("mr_no", mrNo);
  } else {
    patientQuery = patientQuery.eq("patient_token", token);
  }

  const { data: patients, error: patientErr } = await patientQuery.limit(1);

  if (patientErr) {
    console.error("patient lookup", patientErr);
    return jsonResponse(
      { status: "error", message: "Could not verify credentials." },
      500,
      origin,
    );
  }

  const patient = patients?.[0] as Record<string, unknown> | undefined;
  if (!patient) {
    recordFailedLogin(throttleKey);
    return jsonResponse(
      { status: "error", message: "Invalid MR number, token, or PIN." },
      401,
      origin,
    );
  }

  const storedPin = String(patient.pwd ?? "");
  if (!storedPin || !safeEqual(storedPin, pin)) {
    recordFailedLogin(throttleKey);
    return jsonResponse(
      { status: "error", message: "Invalid MR number, token, or PIN." },
      401,
      origin,
    );
  }

  const mr = patient.mr_no as number;
  const { data: tests, error: testsErr } = await supabase
    .from("test_results_all")
    .select("id,category,test_name,test_values,remarks,created_at,status")
    .eq("mr_no", mr)
    .eq("delete_status", false)
    .eq("status", "Completed")
    .order("created_at", { ascending: true });

  if (testsErr) {
    console.error("tests lookup", testsErr);
    return jsonResponse(
      { status: "error", message: "Could not load results." },
      500,
      origin,
    );
  }

  const normalized = (tests || []).map((r) =>
    normalizeTestRow(r as Record<string, unknown>)
  );

  return jsonResponse(
    {
      status: "ok",
      patient: publicPatient(patient),
      tests: normalized,
    },
    200,
    origin,
  );
});
