from pydantic import BaseModel

class GetAllDataFromRegPage(BaseModel):
    salutation : str
    patient_name : str
    relation : str
    relation_name : str
    mobile : str
    gender : str
    age : int
    cnic : str
    patient_token : str | None = "0"
    shift : str
    user : str | None = None
    user_id : str | int | None = None
    user_email : str | None = None
    test_1 : str | int | list | None = None   
    test_2 : str | int | list | None = None   
    test_3 : str | int | list | None = None   
    test_4 : str | int | list | None = None   
    test_5 : str | int | list | None = None   
    test_6 : str | int | list | None = None  
    test_7 : str | int | list | None = None  
    test_8 : str | int | list | None = None
    

class RegisterUser(BaseModel):
    salutation : str
    patient_name : str
    relation : str
    relation_name : str
    mobile : str
    gender : str
    age : int
    cnic : str
    patient_token : str | None = "0"
    shift : str
    

class ChangeVisiblity(BaseModel):
    id : int | str
    include_in_report : str | bool


class FitnessPatientSchema(BaseModel):
    patient_name: str | None = None
    gender: str | None = None
    relation_type: str | None = None
    relation_name: str | None = None
    report_date: str | None = None
    mr_no: str | None = None
    hb: str | None = None
    wbc: str | None = None
    neut: str | None = None
    lymph: str | None = None
    mono: str | None = None
    eosino: str | None = None
    plt: str | None = None
    hiv: str | None = None
    hbsag: str | None = None
    hcv: str | None = None
    vdrl: str | None = None
    user_email: str | None = None