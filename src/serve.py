import uvicorn
import app

print("Starting server")

if __name__ == '__main__':
    uvicorn.run("app:app", host="0.0.0.0", port=8500, reload=True)