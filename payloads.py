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

def split_patient_and_tests(payload:GetAllDataFromRegPage):
    """this function will split the patient basic info name age etc and tests so user can inject/create patient first and get mt
    no and id  then assign tests to him and get results from user 

    Args:
        payload (GetAllDataFromRegPage): same
    """
    payload_patient_info = {
    "salutation" : payload.salutation,
    "patient_name" : payload.patient_name,
    "relation" : payload.relation,
    "relation_name" : payload.relation_name,
    "mobile" : payload.mobile,
    "gender" : payload.gender,
    "age" :  payload.age,
    "cnic" : payload.cnic,
    "patient_token" : payload.patient_token if payload.patient_token and str(payload.patient_token).strip() != "" else "0",
    "shift" : payload.shift,
    "user" : (payload.user or "").strip() or None,
    "user_id" : coerce_user_id(payload.user_id),
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

