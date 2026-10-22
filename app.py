from flask import Flask, jsonify, request
import os
import certifi
import pytds
import requests
import hmac
from datetime import datetime

# ==========================================
# APLICACIÓN FLASK
# ==========================================
app = Flask(__name__)

# ==========================================
# CONEXIÓN A AZURE SQL DATABASE
# ==========================================
def getConection():
    return pytds.connect(
        server=os.environ.get('DB_SERVER'),
        database=os.environ.get('DB_DATABASE'),
        user=os.environ.get('DB_USER'),
        password=os.environ.get('DB_PASS'),
        port=1433,
        cafile=certifi.where(),
        validate_host=True,
        enc_login_only=False
    )

# ==========================================
# SERVICIO SAAS: ENVÍO DE CORREO (BREVO)
# Notificación resumida según diapositivas
# ==========================================
def enviar_correo(destinatario, total_productos):
    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": os.environ.get("BREVO_API_KEY"),
        "content-type": "application/json"
    }

    fecha_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cuerpo_html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 550px; margin: 0 auto; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; background: #ffffff;">
        <div style="background-color: #1e293b; color: #ffffff; padding: 20px; text-align: center;">
            <h2 style="margin: 0; font-size: 20px;">Procesamiento finalizado</h2>
        </div>
        <div style="padding: 25px; color: #334155; font-size: 15px; line-height: 1.6;">
            <p>El procesamiento ha finalizado correctamente.</p>
            
            <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 15px; margin: 20px 0;">
                <p style="margin: 6px 0;"><strong>Proceso:</strong> Consulta de productos</p>
                <p style="margin: 6px 0;"><strong>Detalle:</strong> Se procesaron {total_productos} registros de Azure SQL</p>
                <p style="margin: 6px 0;"><strong>Fecha:</strong> {fecha_hora}</p>
            </div>

            <p style="font-size: 13px; color: #64748b; margin-top: 25px; text-align: center;">
                Notificación automática desde Brevo &bull; Sistema Distribuido UTA
            </p>
        </div>
    </div>
    """

    payload = {
        "sender": {
            "name": "Aplicaciones Distribuidas",
            "email": os.environ.get("EMAIL_REMITENTE")
        },
        "to": [{"email": destinatario}],
        "subject": "Procesamiento finalizado",
        "htmlContent": cuerpo_html
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=15)
    return resp.status_code, resp.text

# ==========================================
# ENDPOINT DE PROCESAMIENTO Y NOTIFICACIÓN
# ==========================================
@app.route('/api/procesar', methods=['POST'])
def procesar_y_notificar():
    api_key_recibida = request.headers.get("X-API-Key", "")
    api_key_servidor = os.environ.get("PROCESS_API_KEY", "")

    if not api_key_recibida or not hmac.compare_digest(api_key_recibida, api_key_servidor):
        return jsonify({"error": "No autorizado: API Key inválida"}), 401

    data = request.get_json(silent=True) or {}
    correo_destino = data.get("correo_cliente") or os.environ.get("EMAIL_DESTINO")

    if not correo_destino:
        return jsonify({"error": "Falta el correo de destino"}), 400

    try:
        conn = getConection()
        cursor = conn.cursor()
        
        # Conteo de registros procesados según la guía
        cursor.execute("SELECT COUNT(*) FROM products_vw")
        total = cursor.fetchone()[0]
        
        cursor.close()
        conn.close()

        # Enviar únicamente la notificación resumida requerida
        codigo_mail, respuesta_mail = enviar_correo(
            destinatario=correo_destino,
            total_productos=total
        )

        if codigo_mail in [200, 201]:
            return jsonify({
                "procesamiento": "finalizado",
                "total_productos": total,
                "notificacion": "enviado",
                "email_destino": correo_destino
            }), 200
        else:
            return jsonify({
                "procesamiento": "finalizado",
                "total_productos": total,
                "notificacion": "fallo",
                "detalle_brevo": respuesta_mail
            }), 502

    except Exception as e:
        return jsonify({
            "mensaje": "Error en el procesamiento",
            "error": str(e)
        }), 500

# ==========================================
# ENDPOINTS REST
# ==========================================
@app.route('/test-db', methods=['GET'])
def test_db():
    try:
        conn = getConection()
        cursor = conn.cursor()
        cursor.execute("SELECT DB_NAME()")
        database = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return jsonify({"mensaje": "Conexion exitosa", "base de datos": database}), 200
    except Exception as e:
        return jsonify({"mensaje": "Error", "error": str(e)}), 500

@app.route('/api/products', methods=['GET'])
def get_products():
    try:
        conn = getConection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, names, price, stock FROM products_vw")
        products = []
        for row in cursor.fetchall():
            products.append({
                "id": row[0],
                "names": str(row[1]),
                "price": float(row[2]),
                "stock": int(row[3])
            })
        cursor.close()
        conn.close()
        return jsonify(products), 200
    except Exception as e:
        return jsonify({"mensaje": "Error", "error": str(e)}), 500

@app.route("/api/products/<int:id>", methods=['GET'])
def get_product(id):
    try:
        conn = getConection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, names, price, stock FROM products_vw WHERE id=%s", (id,))
        row = cursor.fetchone()
        if row:
            product = {
                "id": row[0],
                "names": str(row[1]),
                "price": float(row[2]),
                "stock": int(row[3])
            }
            cursor.close()
            conn.close()
            return jsonify(product), 200

        cursor.close()
        conn.close()
        return jsonify({"mensaje": "producto no existe"}), 404
    except Exception as e:
        return jsonify({"mensaje": "Error", "error": str(e)}), 500

@app.route("/api/products", methods=['POST'])
def create_product():
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"mensaje": "No existen datos validos"}), 400

        names = data.get("names")
        price = data.get("price")
        stock = data.get("stock")

        if not names or price is None or stock is None:
            return jsonify({"mensaje": "Faltan datos requeridos"}), 400

        conn = getConection()
        cursor = conn.cursor()
        cursor.execute("EXEC products_insert_sp %s, %s, %s", (names, price, stock))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"mensaje": "Producto creado exitosamente"}), 201
    except Exception as e:
        return jsonify({"mensaje": "Error al crear producto", "error": str(e)}), 500

if __name__ == '__main__':
    app.run(host="0.0.0.0", debug=True, port=int(os.environ.get("PORT", 5001)))