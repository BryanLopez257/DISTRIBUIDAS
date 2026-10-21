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
        server=os.environ['DB_SERVER'],
        database=os.environ['DB_DATABASE'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASS'],
        port=1433,
        cafile=certifi.where(),
        validate_host=True,
        enc_login_only=False,
        row_strategy=pytds.namedtuple_row_static_strategy
    )

# ==========================================
# SERVICIO SAAS: ENVÍO DE CORREO (BREVO)
# ==========================================
def enviar_correo(destinatario, total_productos, lista_productos):
    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": os.getenv("BREVO_API_KEY"),
        "content-type": "application/json"
    }

    # Filas de la tabla de productos para el correo
    filas_html = ""
    for p in lista_productos:
        filas_html += f"""
        <tr style="border-bottom: 1px solid #e5e7eb;">
            <td style="padding: 10px 14px; text-align: left; font-weight: bold; color: #1f2937;">{p.get('names', 'Sin nombre')}</td>
            <td style="padding: 10px 14px; text-align: center; color: #4b5563;">{p.get('stock', 0)}</td>
            <td style="padding: 10px 14px; text-align: right; font-weight: bold; color: #111827;">${p.get('price', 0):.2f}</td>
        </tr>
        """

    cuerpo_html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; background: #ffffff;">
        <div style="background-color: #111827; color: #ffffff; padding: 25px 20px; text-align: center;">
            <p style="letter-spacing: 2px; font-size: 11px; text-transform: uppercase; margin: 0 0 6px 0; color: #9ca3af;">NUESTRO CATÁLOGO</p>
            <h2 style="margin: 0; font-size: 22px; font-weight: 500;">Productos Disponibles</h2>
        </div>
        <div style="padding: 25px;">
            <p style="color: #4b5563; font-size: 14px; line-height: 1.5; margin-top: 0;">
                Hola. Se ha generado con éxito la consulta del catálogo de productos desde la arquitectura distribuida.
            </p>
            <div style="background: #f9fafb; border: 1px solid #e5e7eb; padding: 10px; border-radius: 6px; text-align: center; margin: 18px 0; font-weight: bold; font-size: 13px; color: #374151;">
                TOTAL DE PRODUCTOS EN CATÁLOGO: {total_productos}
            </div>
            <table style="width: 100%; border-collapse: collapse; font-size: 14px; margin-top: 15px;">
                <thead>
                    <tr style="background: #f3f4f6; color: #6b7280; text-transform: uppercase; font-size: 11px; letter-spacing: 1px;">
                        <th style="padding: 10px 14px; text-align: left;">PRODUCTO</th>
                        <th style="padding: 10px 14px; text-align: center;">STOCK</th>
                        <th style="padding: 10px 14px; text-align: right;">PRECIO</th>
                    </tr>
                </thead>
                <tbody>
                    {filas_html}
                </tbody>
            </table>
            <p style="margin-top: 30px; font-size: 12px; color: #9ca3af; text-align: center;">
                Integración de modelos en la nube: IaaS (Azure VM) + PaaS (Render & Azure SQL) + SaaS (Brevo)
            </p>
        </div>
    </div>
    """

    payload = {
        "sender": {
            "name": "Catálogo Web",
            "email": os.getenv("EMAIL_REMITENTE")
        },
        "to": [{"email": destinatario}],
        "subject": f"Catálogo de Productos ({total_productos} disponibles)",
        "htmlContent": cuerpo_html
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=15)
    return resp.status_code, resp.text

# ==========================================
# ENDPOINT DE PROCESAMIENTO Y NOTIFICACIÓN
# ==========================================
@app.route('/api/procesar', methods=['POST'])
def procesar_y_notificar():
    # 1. Validación de seguridad con la API Key (semilla)
    api_key_recibida = request.headers.get("X-API-Key")
    api_key_servidor = os.getenv("PROCESS_API_KEY", "")

    if not api_key_recibida or not hmac.compare_digest(api_key_recibida, api_key_servidor):
        return jsonify({"error": "No autorizado: API Key inválida"}), 401

    # 2. Correo destino
    data = request.get_json() or {}
    correo_destino = data.get("correo_cliente") or os.getenv("EMAIL_DESTINO")

    if not correo_destino:
        return jsonify({"error": "Falta el correo de destino"}), 400

    try:
        # 3. Consulta a Azure SQL
        conn = getConection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, names, price, stock FROM products_vw")
        
        productos = []
        for row in cursor.fetchall():
            productos.append({
                "id": row[0],
                "names": row[1],
                "price": float(row[2]),
                "stock": int(row[3])
            })
        cursor.close()
        conn.close()

        total = len(productos)

        # 4. Enviar mediante Brevo SaaS
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
                "names": row[1],
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
        cursor.execute("SELECT id, names, price, stock FROM products_vw WHERE id=?", (id,))
        row = cursor.fetchone()
        if row:
            product = {
                "id": row[0],
                "names": row[1],
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
        data = request.get_json()
        if not data:
            return jsonify({"mensaje": "No existen datos validos"}), 400

        names = data.get("names")
        price = data.get("price")
        stock = data.get("stock")

        if not names or price is None or stock is None:
            return jsonify({"mensaje": "Faltan datos requeridos"}), 400

        conn = getConection()
        cursor = conn.cursor()
        cursor.execute("EXEC products_insert_sp ?,?,?", (names, price, stock))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"mensaje": "Producto creado exitosamente"}), 201
    except Exception as e:
        return jsonify({"mensaje": "Error al crear producto", "error": str(e)}), 500

if __name__ == '__main__':
    app.run(host="0.0.0.0", debug=True, port=int(os.environ.get("PORT", 5001)))