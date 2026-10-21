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
        validate_host=True
    )
    

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
                "id": row.id,
                "names": row.names,
                "price": float(row.price),
                "stock": int(row.stock)
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
                "id": row.id,
                "names": row.names,
                "price": float(row.price),
                "stock": int(row.stock)
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
        cursor.execute("EXEC products_insert_sp ?,?,?", names, price, stock)
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"mensaje": "Producto creado exitosamente"}), 201
    except Exception as e:
        return jsonify({"mensaje": "Error al crear producto", "error": str(e)}), 500

if __name__ == '__main__':
    app.run(host="0.0.0.0", debug=True, port=5001)