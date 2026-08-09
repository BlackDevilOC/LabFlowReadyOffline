from schemas import GetAllDataFromRegPage
import json


def coerce_user_id(val):
    if val is None or val == "":
        return None
    s = str(val).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return s


def refine_test(tests):
    modified_test = []

    for test in tests:
        test = str(test)

        if test.isdigit():
            modified_test.append(int(test))
        else:
            list_g_test = json.loads(test)
            for i in list_g_test:
                modified_test.append(int(i))

    return modified_test

def clean_str(val, default="-"):
    if val is None:
        return default
    s = str(val).strip()
    return s if s else default


def clean_age(val):
    if val is None:
        return 0
    s = str(val).strip()
    if not s or s == "-":
        return 0
    try:
        return int(float(s))
    except Exception:
        return 0


def split_patient_and_tests(payload: GetAllDataFromRegPage):
    """Splits patient basic info and tests list, normalizing empty optional fields."""
    payload_patient_info = {
        "salutation": clean_str(payload.salutation, "Mr."),
        "patient_name": str(payload.patient_name or "").strip(),
        "relation": clean_str(payload.relation, "-"),
        "relation_name": clean_str(payload.relation_name, "-"),
        "mobile": clean_str(payload.mobile, "-"),
        "gender": clean_str(payload.gender, "MALE"),
        "age": clean_age(payload.age),
        "cnic": clean_str(payload.cnic, "-"),
        "patient_token": str(payload.patient_token).strip() if payload.patient_token and str(payload.patient_token).strip() != "" else "0",
        "shift": clean_str(payload.shift, "Morning"),
        "user": (payload.user or "").strip() or None,
        "user_id": coerce_user_id(payload.user_id),
    }
    tests = [
        payload.test_1,
        payload.test_2,
        payload.test_3,
        payload.test_4,
        payload.test_5,
        payload.test_6,
        payload.test_7,
        payload.test_8,
        ]
    tests = [t for t in tests if t not in (None, "", 0)]
    tests = refine_test(tests)
    
    return payload_patient_info, tests

