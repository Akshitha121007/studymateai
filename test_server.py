from flask import Flask
app = Flask(__name__)

@app.get("/")
def home():
    return "Server is working!"

app.run(port=3000)