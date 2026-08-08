-- Seed 55+ common lab remarks for testing (safe to re-run).
-- Run in Supabase SQL Editor after create_remarks_table.sql
-- test_name must match test_results_all.test_name / test_groups.group_name exactly.

INSERT INTO remarks (remark_text, test_name, category, sort_order, usage_count)
SELECT v.remark_text, v.test_name, NULL, v.sort_order, v.usage_count
FROM (
  VALUES
    -- Global (all tests) — test_name NULL
    ('Within normal limits.', NULL::text, 1, 120),
    ('Repeat sample required.', NULL, 2, 95),
    ('Quantity not sufficient.', NULL, 3, 88),
    ('Sample received in wrong container.', NULL, 4, 45),
    ('Sample clotted; repeat advised.', NULL, 5, 72),
    ('Sample hemolyzed; interpret with caution.', NULL, 6, 65),
    ('Lipemic sample; results may be affected.', NULL, 7, 40),
    ('Icteric sample; interpret with caution.', NULL, 8, 35),
    ('Result verified on repeat sample.', NULL, 9, 55),
    ('Critical value notified to requesting clinician.', NULL, 10, 30),
    ('Sample rejected — inadequate volume.', NULL, 11, 50),
    ('Delayed report — sample received late.', NULL, 12, 25),
    ('Correlation with clinical findings advised.', NULL, 13, 20),
    ('Previous result on file; trend comparison suggested.', NULL, 14, 18),

    -- Complete Blood Count (CBC) — adjust name if your catalog differs
    ('Repeat CBC — sample clotted.', 'Complete Blood Count (CBC)', 101, 40),
    ('Platelet clumps noted; manual count recommended.', 'Complete Blood Count (CBC)', 102, 22),
    ('Marked leukocytosis; slide review performed.', 'Complete Blood Count (CBC)', 103, 15),
    ('Anemia pattern; peripheral smear advised.', 'Complete Blood Count (CBC)', 104, 12),
    ('Cold agglutinin suspected; repeat at 37°C.', 'Complete Blood Count (CBC)', 105, 8),

    -- Liver Function Test
    ('Hemolyzed sample; AST/ALT may be falsely elevated.', 'Liver Function Test', 201, 28),
    ('Non-fasting sample; lipids may be affected.', 'Liver Function Test', 202, 10),
    ('icteric sample', 'Liver Function Test', 203, 14),

    -- HIV / serology
    ('Reactive screen; confirmatory test advised.', 'HIV (1 & 2)', 301, 35),
    ('Non-reactive.', 'HIV (1 & 2)', 302, 80),
    ('Indeterminate; repeat in 2–4 weeks.', 'HIV (1 & 2)', 303, 12),
    ('Sample received without request form.', 'HIV (1 & 2)', 304, 5),

    ('Non-reactive.', 'HBsAg', 311, 70),
    ('Reactive; confirm with neutralization if applicable.', 'HBsAg', 312, 20),
    ('Sample hemolyzed.', 'HBsAg', 313, 8),

    ('Non-reactive.', 'Anti HCV', 321, 65),
    ('Reactive; repeat recommended.', 'Anti HCV', 322, 18),

    ('Non-reactive.', 'VDRL', 331, 60),
    ('Reactive; titre follow-up advised.', 'VDRL', 332, 15),
    ('Biological false positive possible.', 'VDRL', 333, 6),

    -- Biochemistry singles (use names from your tests table)
    ('Fasting status not confirmed.', 'RBS', 401, 25),
    ('Grossly hemolyzed; glucose may be falsely low.', 'RBS', 402, 18),
    ('Sample not fasting; interpret lipids with caution.', 'UELFT', 411, 20),
    ('Marked hyperbilirubinemia; direct bilirubin suggested.', 'UELFT', 412, 7),
    ('Creatinine elevated; confirm with eGFR/clinical context.', 'Serum Creatinine', 421, 14),
    ('Hemolysis may affect potassium.', 'Serum Electrolytes', 431, 16),

    -- Urine / stool
    ('Sample contaminated; repeat mid-stream urine advised.', 'Urine DR', 501, 30),
    ('Insufficient volume for culture.', 'Urine DR', 502, 12),
    ('Ova not seen; repeat if clinical suspicion persists.', 'Stool DR', 511, 10),
    ('Sample received without preservative.', 'Stool DR', 512, 8),

    -- Hematology
    ('ESR elevated; correlate with CRP/clinical picture.', 'ESR', 601, 12),
    ('Prolonged PT; sample not citrated properly suspected.', 'PT/INR', 611, 15),
    ('Patient on anticoagulant therapy.', 'PT/INR', 612, 25),

    -- Fluid reports
    ('Traumatic tap suspected; repeat if clinically indicated.', 'ASCITIC FLUID DR', 701, 10),
    ('Insufficient fluid for full panel.', 'PLEURAL FLUID FOR DR', 711, 9),

    -- Generic serology label (fallback if test named "HIV" only)
    ('Non-reactive.', 'HIV', 801, 40),
    ('Repeat sample required.', 'HIV', 802, 15),
    ('Non-reactive.', 'CBC', 811, 30),
    ('Sample hemolyzed.', 'CBC', 812, 20)
) AS v(remark_text, test_name, sort_order, usage_count)
WHERE NOT EXISTS (
  SELECT 1
  FROM remarks r
  WHERE lower(trim(r.remark_text)) = lower(trim(v.remark_text))
    AND r.test_name IS NOT DISTINCT FROM v.test_name
);

-- Optional: refresh usage stats for demo (shows "most used" ordering in UI)
-- UPDATE remarks SET usage_count = usage_count WHERE id > 0;
