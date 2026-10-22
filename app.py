from flask import Flask, jsonify, request
import os
import certifi
import pytds
import requests
import hmac

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
# ==========================================
def enviar_correo(destinatario, total_productos, lista_productos):
    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": os.environ.get("BREVO_API_KEY"),
        "content-type": "application/json"
    }

    # Lista sencilla y limpia de los productos
    items_html = ""
    for p in lista_productos:
        items_html += f"""
        <li style="margin-bottom: 8px;">
            <strong>{p.get('names', 'Sin nombre')}</strong> - Precio: ${p.get('price', 0):.2f} (Stock: {p.get('stock', 0)} unidades)
        </li>
        """

    cuerpo_html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 550px; margin: 0 auto; color: #333333; line-height: 1.5;">
        <h2 style="color: #111827; border-bottom: 2px solid #eaeaea; padding-bottom: 10px;">Catálogo de Productos</h2>
        
        <p>Gracias por mostrar interes en nuestro catalogo de productos, a continuacion te compartimos los productos que se encuentran disponibles.</p>
        
        <p><strong>Total de productos disponibles:</strong> {total_productos}</p>
        
        <ul style="padding-left: 20px;">
            {items_html}
        </ul>
        
        <p style="margin-top: 25px; font-size: 13px; color: #666666;">
            Saludos cordiales,<br>
            <strong>Catálogo Web Distribuido</strong>
        </p>
    </div>
    """

    payload = {
        "sender": {
            "name": "Catálogo Web",
            "email": os.environ.get("EMAIL_REMITENTE")
        },
        "to": [{"email": destinatario}],
        "subject": "Productos disponibles - Catálogo Web",
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
        cursor.execute("SELECT id, names, price, stock FROM products_vw")
        
        productos = []
        for row in cursor.fetchall():
            productos.append({
                "id": row[0],
                "names": str(row[1]),
                "price": float(row[2]),
                "stock": int(row[3])
            })
        cursor.close()
        conn.close()

        total = len(productos)

        codigo_mail, respuesta_mail = enviar_correo(
            destinatario=correo_destino,
            total_productos=total,
            lista_productos=productos
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