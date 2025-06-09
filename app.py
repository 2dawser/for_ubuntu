import os
import logging
from flask import Flask, request, jsonify, send_file
from functools import wraps
import paramiko
from io import BytesIO

app = Flask(__name__)

API_TOKEN = os.getenv("API_TOKEN")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def require_token(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != API_TOKEN:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

@app.before_request
def log_request():
    logger.info(f"{request.method} {request.path} from {request.remote_addr}")

@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"Error: {str(e)}", exc_info=True)
    if isinstance(e, (paramiko.ssh_exception.SSHException, ConnectionError)):
        return jsonify({"error": "Error en conexión SFTP", "detail": str(e)}), 500
    return jsonify({"error": "Error interno del servidor", "detail": str(e)}), 500

# Variables SFTP
SFTP_HOST = os.getenv('SFTP_HOST')
SFTP_PORT = int(os.getenv('SFTP_PORT', 22))
SFTP_USERNAME = os.getenv('SFTP_USERNAME')
SFTP_PASSWORD = os.getenv('SFTP_PASSWORD')
SFTP_ROOT = os.getenv('SFTP_ROOT', '/home')
SFTP_INPUT_FOLDER = os.getenv('SFTP_INPUT_FOLDER', 'input')
SFTP_OUTPUT_FOLDER = os.getenv('SFTP_OUTPUT_FOLDER', 'output')

def sftp_connect():
    transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
    transport.connect(username=SFTP_USERNAME, password=SFTP_PASSWORD)
    sftp = paramiko.SFTPClient.from_transport(transport)
    sftp.chdir(SFTP_ROOT)
    return sftp, transport

@app.route("/list", methods=["GET"])
@require_token
def list_files():
    folder = request.args.get("folder")
    if folder not in [SFTP_INPUT_FOLDER, SFTP_OUTPUT_FOLDER]:
        return jsonify({"error": "Folder no permitido"}), 400

    sftp, transport = sftp_connect()
    try:
        sftp.chdir(f"{SFTP_ROOT}/{folder}")
        files = sftp.listdir()
        files = [f"{folder}/{f}" for f in files]
    finally:
        sftp.close()
        transport.close()

    return jsonify({"files": files})

@app.route("/exists", methods=["GET"])
@require_token
def check_exists():
    filename = request.args.get("filename")
    if not filename:
        return jsonify({"error": "Falta parámetro filename"}), 400
    sftp, transport = sftp_connect()
    try:
        sftp.chdir(SFTP_ROOT)
        try:
            sftp.stat(filename)
            exists = True
        except FileNotFoundError:
            exists = False
    finally:
        sftp.close()
        transport.close()

    return jsonify({"exists": exists})

@app.route("/download", methods=["GET"])
@require_token
def download_file():
    filename = request.args.get("filename")
    if not filename:
        return jsonify({"error": "Falta parámetro filename"}), 400

    sftp, transport = sftp_connect()
    try:
        sftp.chdir(SFTP_ROOT)
        with sftp.open(filename, "rb") as f:
            data = f.read()
    finally:
        sftp.close()
        transport.close()

    return send_file(BytesIO(data), download_name=os.path.basename(filename), as_attachment=True)

@app.route("/upload", methods=["POST"])
@require_token
def upload_file():
    if "file" not in request.files or "path" not in request.form:
        return jsonify({"error": "Falta file o path"}), 400

    file = request.files["file"]
    path = request.form["path"]
    if not path.startswith(SFTP_INPUT_FOLDER):
        return jsonify({"error": "Solo se permite subir a la carpeta input"}), 400

    sftp, transport = sftp_connect()
    try:
        sftp.chdir(SFTP_ROOT)
        with sftp.open(path, "wb") as f:
            f.write(file.read())
        sftp.chmod(path, 0o766)
    finally:
        sftp.close()
        transport.close()

    return jsonify({"message": f"Archivo subido a {path} con permisos 0766"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
