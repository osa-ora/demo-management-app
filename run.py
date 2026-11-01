import os
import uvicorn
if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=int(os.environ.get("DM_PORT", "8767")), log_level=os.environ.get("LOG_LEVEL", "info"), access_log=False)
