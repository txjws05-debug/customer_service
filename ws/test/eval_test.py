if __name__=="__main__":
    data={
        "slots":{
            "refund":"test"
        }
    }
    res=bool(eval('slots.get("refund_reason)',{},data))
    print(res)