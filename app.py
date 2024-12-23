from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash,jsonify,session, send_file
from datetime import datetime
import cx_Oracle
from openpyxl import Workbook
from io import BytesIO
import pandas as pd
from flask import send_file

app = Flask(__name__)
app.secret_key = 'saba_1234'

# Konfigurasi koneksi Oracle
dsn = cx_Oracle.makedsn("HCLAB", 1521, service_name="hclab")
conn = cx_Oracle.connect(user="saba", password="saba", dsn=dsn)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:  # Cek apakah user sudah login
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

'''
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # Ambil data login dari form
        user_id = request.form.get('user_id')
        user_password = request.form.get('user_password')

        # Query untuk memeriksa kredensial
        cursor = conn.cursor()
        cursor.execute("""
            SELECT USER_ID, USER_NAME, USER_FLAG 
            FROM USER_TABLE 
            WHERE (USER_ID = :user_id OR USER_NAME = :user_id) AND USER_PASSWORD = :user_password
        """, {'user_id': user_id, 'user_password': user_password})
        user = cursor.fetchone()
        cursor.close()

        if user:
            if user[2] == 'Y':  # Cek apakah akun aktif
                session['user_id'] = user[0]
                session['user_name'] = user[1]
                flash('Login successful!', 'success')
                return redirect(url_for('index'))  # Redirect ke halaman utama
            else:
                flash('Account suspended. Please contact the administrator.', 'danger')
        else:
            flash('Invalid username or password.', 'danger')

    return render_template('login.html')
'''

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # Ambil data login dari form
        user_id = request.form.get('user_id')
        user_password = request.form.get('user_password')

        # Query untuk memeriksa kredensial
        cursor = conn.cursor()
        cursor.execute("""
            SELECT USER_ID, USER_NAME, USER_FLAG, USER_TYPE 
            FROM USER_TABLE 
            WHERE (USER_ID = :user_id OR USER_NAME = :user_id) AND USER_PASSWORD = :user_password
        """, {'user_id': user_id, 'user_password': user_password})
        user = cursor.fetchone()
        cursor.close()

        if user:
            if user[2] == 'Y':  # Cek apakah akun aktif
                session['user_id'] = user[0]
                session['user_name'] = user[1]
                session['user_type'] = user[3]  # Simpan USER_TYPE ke dalam session
                flash('Login successful!', 'success')

                # Arahkan pengguna ke dashboard berdasarkan USER_TYPE
                if user[3] == 'inv':
                    return redirect(url_for('inventory_dashboard'))  # Redirect ke dashboard inventaris
                else:
                    return redirect(url_for('index'))  # Redirect ke halaman utama untuk USER_TYPE lain

            else:
                flash('Account suspended. Please contact the administrator.', 'danger')
        else:
            flash('Invalid username or password.', 'danger')

    return render_template('login.html')



@app.route('/logout')
def logout():
    session.clear()  # Hapus semua data sesi
    flash("You have been logged out.", "info")
    return redirect(url_for('login'))

@app.route('/inventory_dashboard', methods=['GET'])
def inventory_dashboard():
    cursor = conn.cursor()

    # Query to get the list of stock requests
    cursor.execute("""
        SELECT 
            h.request_id,
            d.product_id,
            p.product_name,
            l.location_name,
            d.request_qty,
            h.remark,
            h.tanggal_request
        FROM 
            lab_request_header h
        JOIN lab_request_detail d ON h.request_id = d.request_id
        JOIN product p ON d.product_id = p.product_id
        JOIN location l ON h.location_id = l.location_id
        ORDER BY h.tanggal_request DESC
    """)
    requests = [{
        "request_id": row[0],
        "product_id": row[1],
        "product_name": row[2],
        "location_name": row[3],
        "request_qty": row[4],
        "remark": row[5],
        "tanggal_request": row[6]
    } for row in cursor.fetchall()]


    cursor.close()

 # Get the username from the session
    username = session.get('user_name', 'User')

    return render_template('inventory_dashboard.html', requests=requests, username=username)


@app.route('/')
@login_required
def index():
    # Query for near-expired inventory
    cursor = conn.cursor()
    query_near_expired = """
        SELECT 
            si.product_id, 
            p.product_name, 
            si.batch_no,
            TO_CHAR(si.stock_expired, 'YYYY-MM-DD') AS stock_expired,
            COALESCE(SUM(si.stock_in_qty), 0) - COALESCE(SUM(so.stock_out_qty), 0) AS current_stock
        FROM 
            product p
        LEFT JOIN 
            stock_in si ON p.product_id = si.product_id
        LEFT JOIN 
            stock_out so ON p.product_id = so.product_id AND si.batch_no = so.batch_no
        WHERE 
            si.stock_expired < ADD_MONTHS(SYSDATE, 2)
        GROUP BY 
            si.product_id, p.product_name, si.batch_no, si.stock_expired
    """
    cursor.execute(query_near_expired)
    rows_near_expired = cursor.fetchall()

    inventory = [
        {
            "product_id": row[0],
            "product_name": row[1],
            "batch_no": row[2],
            "stock_expired": row[3],
            "current_stock": row[4]
        }
        for row in rows_near_expired
    ]

    # Query for full inventory data
    query_inventory = """
      WITH stock_out_agg AS (
        SELECT 
            product_id, 
            SUM(stock_out_qty) AS total_stock_out
        FROM 
            stock_out
        GROUP BY 
            product_id
    ),
    stock_in_agg AS (
        SELECT 
            product_id, 
            SUM(stock_in_qty) AS total_stock_in
        FROM 
            stock_in
        GROUP BY 
            product_id
    )
    SELECT 
        p.product_id, 
        p.product_name, 
        s.supp_name, 
        m.manu_name,
        COALESCE(si.total_stock_in, 0) AS stock_in,
        COALESCE(so.total_stock_out, 0) AS stock_out,
        COALESCE(si.total_stock_in, 0) - COALESCE(so.total_stock_out, 0) AS current_stock,
        p.safety_level
    FROM 
        product p
    LEFT JOIN 
        supplier s ON p.supplier_id = s.supplier_id
    LEFT JOIN 
        manufacture m ON p.manu_id = m.manu_id
    LEFT JOIN 
        stock_in_agg si ON p.product_id = si.product_id
    LEFT JOIN 
        stock_out_agg so ON p.product_id = so.product_id
    WHERE 
        (COALESCE(si.total_stock_in, 0) - COALESCE(so.total_stock_out, 0)) <= p.safety_level
    ORDER BY 
        p.product_name ASC
    """
    cursor.execute(query_inventory)
    rows_inventory = cursor.fetchall()

    inventorys = [
        {
            "product_id": row[0], 
            "product_name": row[1], 
            "supp_name": row[2], 
            "manu_name": row[3],
            "stock_in": row[4],
            "stock_out": row[5],
            "current_stock": row[6],
            "safety_level": row[7]
        }
        for row in rows_inventory
    ]

    cursor.close()

    # Get the username from the session
    username = session.get('user_name', 'User')

    return render_template('index.html', inventory=inventory, inventorys=inventorys, username=username)

# Route Master Manufacture--------------------------------------------------------------------------------------------------
@app.route('/master_manufacture')
def master_manufacture():
    search_query= request.args.get('search', '')  # Ambil query pencarian dari input
    cursor=conn.cursor()

    if search_query:
        cursor.execute("SELECT manu_id, manu_name, manu_country FROM manufacture WHERE LOWER(manu_name) LIKE :search_query", {
            "search_query": f"%{search_query.lower()}%"
        })
    else:
        cursor.execute("SELECT manu_id, manu_name, manu_country FROM manufacture order by manu_name asc")

    manufactures = [{"manu_id": row[0], "manu_name": row[1], "manu_country": row[2]} for row in cursor.fetchall()]
    cursor.close()

    return render_template('master_manufacture.html', manufactures=manufactures)

    # Route Untuk Tambah Manufacuture
@app.route('/tambah_manufacture', methods=['GET', 'POST'])
def tambah_manufacture():
    if request.method == 'POST':
        # Ambil data dari form
        manu_id = request.form['manu_id']
        manu_name = request.form['manu_name']
        manu_country = request.form['manu_country']

        cursor = conn.cursor()
        # Validasi: Cek apakah manu_id sudah ada
        cursor.execute("SELECT COUNT(*) FROM manufacture WHERE manu_id = :manu_id", {"manu_id": manu_id})
        count = cursor.fetchone()[0]
        
        if count > 0:
            flash("Manufacture ID sudah ada. Gunakan ID yang lain.", "danger")
            cursor.close()
            return redirect(url_for('tambah_manufacture'))

        # Jika validasi lolos, masukkan data ke database
        try:
            cursor.execute(
                "INSERT INTO manufacture (manu_id, manu_name, manu_country) VALUES (:manu_id, :manu_name, :manu_country)",
                {"manu_id": manu_id, "manu_name": manu_name, "manu_country": manu_country}
            )
            conn.commit()
            flash("Manufacture berhasil ditambahkan", "success")
        except cx_Oracle.DatabaseError as e:
            flash(f"Gagal menambahkan manufacture: {str(e)}", "danger")
        finally:
            cursor.close()

        return redirect(url_for('master_manufacture'))  # Arahkan ke halaman master manufacture setelah tambah

    # Jika method GET, tampilkan halaman tambah manufacture
    return render_template('tambah_manufacture.html')

    # Route untuk edit manufacture
@app.route('/edit_manufacture/<manu_id>', methods=['GET', 'POST'])
def edit_manufacture(manu_id):
    cursor = conn.cursor()

    if request.method == 'POST':
        # Ambil data dari form
        manu_name = request.form['manu_name']
        manu_country = request.form['manu_country']

        try:
            # Update data manufacture
            cursor.execute(
                "UPDATE manufacture SET manu_name = :manu_name, manu_country = :manu_country WHERE manu_id = :manu_id",
                {"manu_name": manu_name, "manu_country": manu_country, "manu_id": manu_id}
            )
            conn.commit()
            flash("manufacture berhasil diperbarui", "success")
        except cx_Oracle.DatabaseError as e:
            flash(f"Gagal memperbarui manufacture: {str(e)}", "danger")
        finally:
            cursor.close()

        return redirect(url_for('master_manufacture'))  # Redirect ke halaman master_manufacture setelah update

    # Ambil data lokasi berdasarkan manu_id
    cursor.execute("SELECT manu_id, manu_name, manu_country FROM manufacture WHERE manu_id = :manu_id", {"manu_id": manu_id})
    manufacture = cursor.fetchone()
    cursor.close()

    if manufacture:
        manu_data = {"manu_id": manufacture[0], "manu_name": manufacture[1], "manu_country": manufacture[2]}
        return render_template('edit_manufacture.html', manufacture=manu_data)
    else:
        flash("manufacture tidak ditemukan", "danger")
        return redirect(url_for('master_manufacture'))

# Route untuk hapus manufacture
@app.route('/delete_manufacture/<manu_id>', methods=['GET'])
def delete_manufacture(manu_id):
    cursor = conn.cursor()

    try:
        # Hapus lokasi berdasarkan manu_id
        cursor.execute("DELETE FROM manufacture WHERE manu_id = :manu_id", {"manu_id": manu_id})
        conn.commit()
        flash("manufacture berhasil dihapus", "success")
    except cx_Oracle.DatabaseError as e:
        flash(f"Gagal menghapus manufacture: {str(e)}", "danger")
    finally:
        cursor.close()

    return redirect(url_for('master_manufacture'))  # Redirect kembali ke halaman master__manufacture

# Dummy data untuk demonstration
suppliers = [
    {
        "SUPPLIER_ID": 1,
        "SUPP_NAME": "Supplier A",
        "SUPP_ADDRESS": "Jl. Merpati No. 1",
        "SUPP_REGION": "Jakarta",
        "SUPP_TELP": "08123456789",
        "SUPP_EMAIL": "supplierA@example.com",
        "SUPP_FLAG": "Active"
    },
    {
        "SUPPLIER_ID": 2,
        "SUPP_NAME": "Supplier B",
        "SUPP_ADDRESS": "Jl. Kakatua No. 5",
        "SUPP_REGION": "Bandung",
        "SUPP_TELP": "08198765432",
        "SUPP_EMAIL": "supplierB@example.com",
        "SUPP_FLAG": "Inactive"
    },
]

@app.route('/master_supplier', methods=['GET'])
def master_supplier():
    search_query = request.args.get('search', '')
    filtered_suppliers = [
        supplier for supplier in suppliers if search_query.lower() in supplier["SUPP_NAME"].lower()
    ] if search_query else suppliers
    return render_template('master_supplier.html', suppliers=filtered_suppliers)

@app.route('/tambah_supplier', methods=['GET', 'POST'])
def tambah_supplier():
    if request.method == 'POST':
        new_supplier = {
            "SUPPLIER_ID": len(suppliers) + 1,
            "SUPP_NAME": request.form['SUPP_NAME'],
            "SUPP_ADDRESS": request.form['SUPP_ADDRESS'],
            "SUPP_REGION": request.form['SUPP_REGION'],
            "SUPP_TELP": request.form['SUPP_TELP'],
            "SUPP_EMAIL": request.form['SUPP_EMAIL'],
            "SUPP_FLAG": "Active",
        }
        suppliers.append(new_supplier)
        return redirect(url_for('master_supplier'))
    return render_template('tambah_supplier.html')

@app.route('/edit_supplier/<int:supplier_id>', methods=['GET', 'POST'])
def edit_supplier(supplier_id):
    supplier = next((s for s in suppliers if s["SUPPLIER_ID"] == supplier_id), None)
    if request.method == 'POST':
        supplier.update({
            "SUPP_NAME": request.form['SUPP_NAME'],
            "SUPP_ADDRESS": request.form['SUPP_ADDRESS'],
            "SUPP_REGION": request.form['SUPP_REGION'],
            "SUPP_TELP": request.form['SUPP_TELP'],
            "SUPP_EMAIL": request.form['SUPP_EMAIL'],
        })
        return redirect(url_for('master_supplier'))
    return render_template('edit_supplier.html', supplier=supplier)

@app.route('/delete_supplier/<int:supplier_id>', methods=['GET'])
def delete_supplier(supplier_id):
    global suppliers
    suppliers = [s for s in suppliers if s["SUPPLIER_ID"] != supplier_id]
    return redirect(url_for('master_supplier'))


# Route Master Product-----------------------------------------------------------------------------------------------------------------
@app.route('/master_product')
def master_product():
    search_query = request.args.get('search', '')  # Ambil query pencarian dari input
    cursor = conn.cursor()

    base_query = """
        SELECT a.product_id, 
               a.product_name, 
               b.type_name, 
               c.manu_name, 
               d.supp_name, 
               e.unit_name, 
               f.location_name,
               a.safety_level
        FROM product a
        JOIN product_type b ON a.type_id = b.type_id
        JOIN manufacture c ON a.manu_id = c.manu_id
        JOIN supplier d ON a.supplier_id = d.supplier_id
        JOIN unit e ON a.unit_id = e.unit_id
        JOIN location f ON a.location_id = f.location_id
    """

    if search_query:
        search_condition = """
            WHERE LOWER(a.product_name) LIKE :search_query 
            OR LOWER(b.type_name) LIKE :search_query 
            OR LOWER(c.manu_name) LIKE :search_query 
            OR LOWER(d.supp_name) LIKE :search_query
        """
        full_query = base_query + search_condition + " ORDER BY a.product_name ASC"
        cursor.execute(full_query, {
            "search_query": f"%{search_query.lower()}%"
        })
    else:
        full_query = base_query + " ORDER BY a.product_name ASC"
        cursor.execute(full_query)

    products = [{
        "product_id": row[0], 
        "product_name": row[1], 
        "type_name": row[2],
        "manu_name": row[3],
        "supp_name": row[4],
        "unit_name": row[5],
        "location_name": row[6],
        "safety_level": row[7]
    } for row in cursor.fetchall()]
    
    cursor.close()

    return render_template('master_product.html', products=products)

#Route tambah product
@app.route('/tambah_product', methods=['GET', 'POST'])
def tambah_product():
    cursor = conn.cursor()

    #Dropdown manufacture
    cursor.execute("SELECT manu_id, manu_name FROM manufacture")
    manufactures = cursor.fetchall()

    #Dropdown supplier
    cursor.execute("SELECT supplier_id, supp_name FROM supplier")
    suppliers = cursor.fetchall()

    #Dropdown Unit
    cursor.execute("SELECT unit_id, unit_name FROM unit")
    units = cursor.fetchall()

    #Dropdown location
    cursor.execute("SELECT location_id, location_name FROM location where location_type='Warehouse'")
    locations = cursor.fetchall()

    #Dropdown type
    cursor.execute("SELECT type_id, type_name FROM product_type")
    types = cursor.fetchall()

    cursor.close()

    if request.method == 'POST':
        product_name = request.form.get('product_name')
        type_id = request.form.get('type_dropdown')
        manu_id = request.form.get('manu_dropdown')
        supplier_id = request.form.get('supplier_dropdown')
        unit_id = request.form.get('unit_dropdown')
        location_id = request.form.get('location_dropdown')
        safety_level = request.form.get('safety_level')

        # Check if any required field is None (indicating a missing selection)
        if None in (product_name, type_id, manu_id, supplier_id, unit_id, location_id, safety_level):
            flash("Please fill in all fields.", "danger")
            return redirect(url_for('tambah_product'))  # Redirect back to the form

        cursor = conn.cursor()

        # Step 1: Fetch the last product_id for the given type_id
        cursor.execute("""
                        SELECT product_id FROM (
                            SELECT product_id FROM product 
                            WHERE product_id LIKE :type_prefix 
                            ORDER BY product_id DESC
                        ) WHERE ROWNUM = 1
                    """, {'type_prefix': f"{type_id}%"})
        
        last_product_id = cursor.fetchone()
        
        # Step 2: Generate the new product_id
        if last_product_id is not None:
            last_id = last_product_id[0]
            # Extract the numeric part and increment it
            numeric_part = int(last_id[2:])  # Assuming product_id format is like RG0001
            new_numeric_part = numeric_part + 1
        else:
            new_numeric_part = 1  # Start from 1 if no previous id exists

        # Format the new product_id
        new_product_id = f"{type_id}{new_numeric_part:04d}"  # e.g., RG0001, BH0001, OT0001

        # Step 3: Insert the new product with the generated product_id
        cursor.execute("""
            INSERT INTO product (product_id, product_name, type_id, manu_id, supplier_id, unit_id, location_id, safety_level)
            VALUES (:product_id, :product_name, :type_id, :manu_id, :supplier_id, :unit_id, :location_id, :safety_level)
        """, {
            "product_id": new_product_id,
            "product_name": product_name,
            "type_id": type_id,
            "manu_id": manu_id,
            "supplier_id": supplier_id,
            "unit_id": unit_id,
            "location_id": location_id,
            "safety_level": safety_level
        })
        
        conn.commit()
        cursor.close()

        return redirect(url_for('master_product'))

    return render_template('tambah_product.html', 
                           manufactures=manufactures, 
                           suppliers=suppliers, 
                           units=units, 
                           locations=locations,
                           types=types)  # Halaman untuk menambah produk


@app.route('/edit_product/<product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    cursor = conn.cursor()

    if request.method == 'POST':
        product_name = request.form.get('product_name')
        type_id = request.form.get('type_id')
        manu_id = request.form.get('manu_id')
        supplier_id = request.form.get('supplier_id')
        unit_id = request.form.get('unit_id')
        location_id = request.form.get('location_id')
        safety_level = request.form.get('safety_level')

        cursor.execute("""
            UPDATE product
            SET product_name = :product_name, 
                type_id = :type_id, 
                manu_id = :manu_id, 
                supplier_id = :supplier_id, 
                unit_id = :unit_id, 
                location_id = :location_id, 
                safety_level = :safety_level
            WHERE product_id = :product_id
        """, {
            "product_name": product_name,
            "type_id": type_id,
            "manu_id": manu_id,
            "supplier_id": supplier_id,
            "unit_id": unit_id,
            "location_id": location_id,
            "safety_level": safety_level,
            "product_id": product_id
        })
        conn.commit()
        cursor.close()

        return redirect(url_for('master_product'))

    # Fetch product data based on product_id
    cursor.execute("SELECT * FROM product WHERE product_id = :product_id", {"product_id": product_id})
    product = cursor.fetchone()

    # Fetch options for dropdowns
    cursor.execute("SELECT type_id, type_name FROM product_type")  # Adjust query as necessary
    types = cursor.fetchall()
    
    cursor.execute("SELECT manu_id, manu_name FROM manufacture")  # Adjust query as necessary
    manufactures = cursor.fetchall()
    
    cursor.execute("SELECT supplier_id, supp_name FROM supplier")  # Adjust query as necessary
    suppliers = cursor.fetchall()
    
    cursor.execute("SELECT unit_id, unit_name FROM unit")  # Adjust query as necessary
    units = cursor.fetchall()
    
    cursor.execute("SELECT location_id, location_name FROM location where location_type='Warehouse'")
    locations = cursor.fetchall()

    cursor.close()

    return render_template('edit_product.html', product=product, types=types, manufactures=manufactures, suppliers=suppliers, units=units, locations=locations)

# Route Delete product
@app.route('/delete_product/<product_id>', methods=['POST'])  # Change to POST
def delete_product(product_id):
    cursor = conn.cursor()

    try:
        # Hapus product berdasarkan product_id
        cursor.execute("DELETE FROM product WHERE product_id = :product_id", {"product_id": product_id})  # Correct binding
        conn.commit()
        flash("Product berhasil dihapus", "success")
    except cx_Oracle.DatabaseError as e:
        flash(f"Gagal menghapus product: {str(e)}", "danger")
    finally:
        cursor.close()

    return redirect(url_for('master_product'))  # Redirect kembali ke halaman product




# Route Master Location-----------------------------------------------------------------------------------------------------------------
@app.route('/master_location')
def master_location():
    search_query = request.args.get('search', '')  # Ambil query pencarian dari input
    cursor = conn.cursor()

    if search_query:
        cursor.execute("SELECT location_id, location_name, location_type FROM location WHERE LOWER(location_name) LIKE :search_query", {
            "search_query": f"%{search_query.lower()}%"
        })
    else:
        cursor.execute("SELECT location_id, location_name, location_type FROM location order by location_type desc")

    locations = [{"location_id": row[0], "location_name": row[1], "location_type": row[2]} for row in cursor.fetchall()]
    cursor.close()

    return render_template('master_location.html', locations=locations)


# Route Untuk Tambah Location
@app.route('/tambah_location', methods=['GET', 'POST'])
def tambah_location():
    if request.method == 'POST':
        # Ambil data dari form
        location_id = request.form['location_id']
        location_name = request.form['location_name']
        location_type = request.form['location_type']

        cursor = conn.cursor()
        # Validasi: Cek apakah location_id sudah ada
        cursor.execute("SELECT COUNT(*) FROM location WHERE location_id = :location_id", {"location_id": location_id})
        count = cursor.fetchone()[0]
        
        if count > 0:
            flash("Location ID sudah ada. Gunakan ID yang lain.", "danger")
            cursor.close()
            return redirect(url_for('tambah_location'))

        # Jika validasi lolos, masukkan data ke database
        try:
            cursor.execute(
                "INSERT INTO location (location_id, location_name, location_type) VALUES (:location_id, :location_name, :location_type)",
                {"location_id": location_id, "location_name": location_name, "location_type": location_type}
            )
            conn.commit()
            flash("Location berhasil ditambahkan", "success")
        except cx_Oracle.DatabaseError as e:
            flash(f"Gagal menambahkan location: {str(e)}", "danger")
        finally:
            cursor.close()

        return redirect(url_for('master_location'))  # Arahkan ke halaman master location setelah tambah

    # Jika method GET, tampilkan halaman tambah location
    return render_template('tambah_location.html')

# Route untuk edit Location
@app.route('/edit_location/<location_id>', methods=['GET', 'POST'])
def edit_location(location_id):
    cursor = conn.cursor()

    if request.method == 'POST':
        # Ambil data dari form
        location_name = request.form['location_name']
        location_type = request.form['location_type']

        try:
            # Update data lokasi
            cursor.execute(
                "UPDATE location SET location_name = :location_name, location_type = :location_type WHERE location_id = :location_id",
                {"location_name": location_name, "location_type": location_type, "location_id": location_id}
            )
            conn.commit()
            flash("Location berhasil diperbarui", "success")
        except cx_Oracle.DatabaseError as e:
            flash(f"Gagal memperbarui location: {str(e)}", "danger")
        finally:
            cursor.close()

        return redirect(url_for('master_location'))  # Redirect ke halaman master_location setelah update

    # Ambil data lokasi berdasarkan location_id
    cursor.execute("SELECT location_id, location_name, location_type FROM location WHERE location_id = :location_id", {"location_id": location_id})
    location = cursor.fetchone()
    cursor.close()

    if location:
        location_data = {"location_id": location[0], "location_name": location[1], "location_type": location[2]}
        return render_template('edit_location.html', location=location_data)
    else:
        flash("Location tidak ditemukan", "danger")
        return redirect(url_for('master_location'))

# Route untuk hapus Location
@app.route('/delete_location/<location_id>', methods=['GET'])
def delete_location(location_id):
    cursor = conn.cursor()

    try:
        # Hapus lokasi berdasarkan location_id
        cursor.execute("DELETE FROM location WHERE location_id = :location_id", {"location_id": location_id})
        conn.commit()
        flash("Location berhasil dihapus", "success")
    except cx_Oracle.DatabaseError as e:
        flash(f"Gagal menghapus location: {str(e)}", "danger")
    finally:
        cursor.close()

    return redirect(url_for('master_location'))  # Redirect kembali ke halaman master_location


# Route Master Unit------------------------------------------------------------------------------------------------------------------------
@app.route('/master_unit')
def master_unit():
    search_query = request.args.get('search', '')  # Ambil query pencarian dari input
    cursor = conn.cursor()

    if search_query:
        cursor.execute("SELECT unit_id, unit_name FROM unit WHERE LOWER(unit_name) LIKE :search_query", {
            "search_query": f"%{search_query.lower()}%"
        })
    else:
        cursor.execute("SELECT unit_id, unit_name FROM unit")

    units = [{"unit_id": row[0], "unit_name": row[1]} for row in cursor.fetchall()]
    cursor.close()

    return render_template('master_unit.html', units=units)

# Route untuk Tambah Unit
@app.route('/tambah_unit', methods=['GET', 'POST'])
def tambah_unit():
    if request.method == 'POST':
        # Ambil data dari form
        unit_id = request.form['unit_id']
        unit_name = request.form['unit_name']

        # Simpan data ke database
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO unit (unit_id, unit_name) VALUES (:1, :2)",
            (unit_id, unit_name)
        )
        conn.commit()
        cursor.close()

        # Redirect kembali ke halaman master unit
        return redirect(url_for('master_unit'))

    else:
        # Generate unit_id otomatis
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(unit_id) FROM unit WHERE unit_id LIKE 'U%'")
        result = cursor.fetchone()[0]
        cursor.close()

        # Tentukan unit_id berikutnya
        if result:
            last_number = int(result[1:])  # Ambil angka setelah 'U'
            next_number = last_number + 1
        else:
            next_number = 1  # Jika tidak ada data, mulai dari 1

        unit_id = f"U{next_number:04}"  # Format ID menjadi 'U0001', 'U0002', dst.

        # Tampilkan form tambah unit
        return render_template('tambah_unit.html', unit_id=unit_id)

# Route untuk Edit Unit
@app.route('/edit_unit/<unit_id>', methods=['GET', 'POST'])
def edit_unit(unit_id):
    cursor = conn.cursor()

    if request.method == 'POST':
        unit_name = request.form['unit_name']
        cursor.execute("UPDATE unit SET unit_name = :unit_name WHERE unit_id = :unit_id", {
            "unit_name": unit_name,
            "unit_id": unit_id
        })
        conn.commit()
        cursor.close()

        flash("Unit berhasil diperbarui", "success")
        return redirect(url_for('master_unit'))

    cursor.execute("SELECT unit_id, unit_name FROM unit WHERE unit_id = :unit_id", {"unit_id": unit_id})
    unit = cursor.fetchone()
    cursor.close()

    return render_template('edit_unit.html', unit={"unit_id": unit[0], "unit_name": unit[1]})

# Route untuk Hapus Unit
@app.route('/delete_unit/<unit_id>')
def delete_unit(unit_id):
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM unit WHERE unit_id = :unit_id", {"unit_id": unit_id})
        conn.commit()
        cursor.close()
        flash("Unit berhasil dihapus", "success")
    except cx_Oracle.DatabaseError as e:
        flash(f"Gagal menghapus unit: {str(e)}", "danger")

    return redirect(url_for('master_unit'))

# Route Master Inventory-----------------------------------------------------------------------------------------------------------------
@app.route('/inventory_data')
def inventory_data():
    cursor = conn.cursor()

    base_query = """
        WITH stock_out_agg AS (
            SELECT 
                product_id, 
                SUM(stock_out_qty) AS total_stock_out
            FROM 
                stock_out
            GROUP BY 
                product_id
        ),
        stock_in_agg AS (
            SELECT 
                product_id, 
                SUM(stock_in_qty) AS total_stock_in
            FROM 
                stock_in
            GROUP BY 
                product_id
        )
        SELECT 
            p.product_id, 
            p.product_name, 
            s.supp_name, 
            m.manu_name,
            COALESCE(si.total_stock_in, 0) AS stock_in,
            COALESCE(so.total_stock_out, 0) AS stock_out,
            COALESCE(si.total_stock_in, 0) - COALESCE(so.total_stock_out, 0) AS current_stock,
            p.safety_level
        FROM 
            product p
        LEFT JOIN 
            supplier s ON p.supplier_id = s.supplier_id
        LEFT JOIN 
            manufacture m ON p.manu_id = m.manu_id
        LEFT JOIN 
            stock_in_agg si ON p.product_id = si.product_id
        LEFT JOIN 
            stock_out_agg so ON p.product_id = so.product_id
        ORDER BY 
            p.product_name ASC

    """

    # Execute the query without any search condition
    cursor.execute(base_query)

    # Fetch all rows from the executed query
    rows = cursor.fetchall()

    # Debugging: Log the number of results
    # print(f"Number of rows returned: {len(rows)}")  # Log the number of rows returned

    # Create a list of dictionaries from the fetched rows
    inventorys = [{
        "product_id": row[0], 
        "product_name": row[1], 
        "supp_name": row[2], 
        "manu_name": row[3],
        "stock_in": row[4],
        "stock_out": row[5],
        "current_stock": row[6],
        "safety_level": row[7]
    } for row in rows]
    
    cursor.close()
    print(inventorys)

    return render_template('inventory_data.html', inventorys=inventorys)

#Route Stock In
@app.route('/stock_in', methods=['GET', 'POST'])
def stock_in():
    cursor = conn.cursor()

    # Fetch dropdown product data
    cursor.execute("SELECT product_id, product_name, type_id FROM product")
    products = cursor.fetchall()
    cursor.close()

    if request.method == 'POST':
        product_id = request.form.get('product_id')
        batch_no = request.form.get('batch_no')
        do_no = request.form.get('do_no')
        stock_in_date = request.form.get('stock_in_date')
        stock_in_qty = request.form.get('stock_in_qty')
        stock_expired_date = request.form.get('stock_expired_date') or None
        remarks = request.form.get('remarks') or None
        update_by = 'RTS'
        update_on = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Validate product type
        cursor = conn.cursor()
        cursor.execute("SELECT type_id FROM product WHERE product_id = :product_id", {"product_id": product_id})
        type_id = cursor.fetchone()
        cursor.close()

        if type_id in ['RG', 'BH']:
            if not batch_no or not stock_expired_date:
                flash("Batch No dan Expired Date wajib diisi untuk tipe RG atau BH", "danger")
                return redirect(url_for('stock_in'))

        # Fetch sequence value
        cursor = conn.cursor()
        cursor.execute("SELECT stock_in_seq.NEXTVAL FROM dual")
        sequence_value = cursor.fetchone()[0]
        cursor.close()

        # Generate ID_STOCK_IN
        id_stock_in = f"SI24{sequence_value:08d}"

        # Insert data
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO stock_in (id_stock_in, product_id, batch_no, do_no, stock_in_date, stock_in_qty, stock_expired, remark, update_by, update_on)
            VALUES (:id_stock_in, :product_id, :batch_no, :do_no, TO_DATE(:stock_in_date, 'YYYY-MM-DD'), :stock_in_qty, TO_DATE(:stock_expired_date, 'YYYY-MM-DD'), :remarks, :update_by, TO_DATE(:update_on, 'YYYY-MM-DD HH24:MI:SS'))
        """, {
            "id_stock_in": id_stock_in,
            "product_id": product_id,
            "batch_no": batch_no,
            "do_no": do_no,
            "stock_in_date": stock_in_date,
            "stock_in_qty": stock_in_qty,
            "stock_expired_date": stock_expired_date,
            "remarks": remarks,
            "update_by": update_by,
            "update_on": update_on
        })

        conn.commit()
        cursor.close()

        return redirect(url_for('inventory_data'))

    return render_template('stock_in.html', products=products)

'''
#Route Stock In
@app.route('/stock_in', methods=['GET', 'POST'])
def stock_in():
    # Membuka koneksi dan cursor
    cursor = conn.cursor()

    # Dropdown product_id
    cursor.execute("SELECT product_id, product_name FROM product")
    products = cursor.fetchall()
    cursor.close()

    if request.method == 'POST':
        product_id = request.form.get('product_id')  # Ambil product_id dari form
        batch_no = request.form.get('batch_no')
        do_no = request.form.get('do_no')
        stock_in_date = request.form.get('stock_in_date')
        stock_in_qty = request.form.get('stock_in_qty')
        stock_expired_date = request.form.get('stock_expired_date') or None
        remarks = request.form.get('remarks') or None
        update_by = 'RTS'
        update_on = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Ambil nilai dari sequence
        cursor = conn.cursor()
        cursor.execute("SELECT stock_in_seq.NEXTVAL FROM dual")
        sequence_value = cursor.fetchone()[0]
        cursor.close()

        # Format ID_STOCK_IN
        id_stock_in = f"SI24{sequence_value:08d}"  # Format SI24000001

        # Membuka koneksi dan cursor untuk INSERT
        cursor = conn.cursor()

        # Step 3: Insert the new product with the selected product_id
        cursor.execute("""
            INSERT INTO stock_in (id_stock_in, product_id, batch_no, do_no, stock_in_date, stock_in_qty, stock_expired, remark, update_by, update_on)
            VALUES (:id_stock_in, :product_id, :batch_no, :do_no, TO_DATE(:stock_in_date, 'YYYY-MM-DD'), :stock_in_qty, TO_DATE(:stock_expired_date, 'YYYY-MM-DD'), :remarks, :update_by, TO_DATE(:update_on, 'YYYY-MM-DD HH24:MI:SS'))
        """, {
            "id_stock_in": id_stock_in,
            "product_id": product_id,  # Pastikan product_id diambil dari form
            "batch_no": batch_no,
            "do_no": do_no,
            "stock_in_date": stock_in_date,
            "stock_in_qty": stock_in_qty,
            "stock_expired_date": stock_expired_date,
            "remarks": remarks,
            "update_by": update_by,
            "update_on": update_on
        })

        conn.commit()
        cursor.close()

        return redirect(url_for('inventory_data'))

    return render_template('stock_in.html', products=products)  # Halaman untuk menambah produk
'''
#Route stock_in_data---------------------------------------------------------------------------------------------------------
@app.route('/stockin_data')
def stockin_data():
    search_query = request.args.get('search', '')
    cursor = conn.cursor()

    base_query = """
        SELECT 
            si.id_stock_in,
            si.stock_in_date,
            si.product_id, 
            p.product_name,
            si.batch_no,
            si.do_no,
            si.stock_in_qty,
            si.stock_expired,
            s.supp_name, 
            m.manu_name
        FROM 
            stock_in  si
        LEFT JOIN
            product p ON si.product_id = p.product_id
        LEFT JOIN 
            supplier s ON p.supplier_id = s.supplier_id
        LEFT JOIN 
            manufacture m ON p.manu_id = m.manu_id
    """
    if search_query:
        search_condition = """
            WHERE LOWER(si.id_stock_in) LIKE :search_query 
            OR LOWER(p.product_name) LIKE :search_query 
            OR LOWER(si.do_no) LIKE :search_query 
            OR LOWER(s.supp_name) LIKE :search_query
        """
        full_query = base_query + search_condition + " ORDER BY si.stock_in_date DESC"
        cursor.execute(full_query, {
            "search_query": f"%{search_query.lower()}%"
        })
    else:
        full_query = base_query + " ORDER BY si.stock_in_date DESC"
        ##print(full_query)
        cursor.execute(full_query)
    

    # Fetch all rows from the executed query
    rows = cursor.fetchall()

    # Debugging: Log the number of results
    # print(f"Number of rows returned: {len(rows)}")  # Log the number of rows returned

    # Create a list of dictionaries from the fetched rows
    stockindata = [{
        "id_stock_in": row[0], 
        "stock_in_date": row[1],
        "product_id": row[2],
        "product_name": row[3],
        "batch_no": row[4],
        "do_no": row[5],
        "stock_in_qty": row[6],
        "stock_expired": row[7],
        "supp_name": row[8],
        "manu_name": row[9]
        
    } for row in rows]
    
    cursor.close()
    print(stockindata)

    return render_template('stock_in_data.html', stockindata=stockindata)

@app.route('/stock_out/<string:request_id>', methods=['GET', 'POST'])
def stock_out(request_id):
    # Open a cursor to fetch data
    cursor = conn.cursor()

    # Fetch product_id and qty from lab_request_detail based on request_id
    cursor.execute("""
        SELECT lr.product_id, p.product_name, lr.request_qty
        FROM lab_request_detail lr
        JOIN product p ON lr.product_id = p.product_id
        WHERE lr.request_id = :request_id
    """, {"request_id": request_id})
    lab_request_details = cursor.fetchall()
    lab_request_details = [
        {
            "product_id": row[0],
            "product_name": row[1],
            "request_qty": row[2]
        }
        for row in lab_request_details
    ]

    # Fetch batch numbers for stock out
    cursor.execute("""
        SELECT s.batch_no
        FROM lab_request_detail lr
        JOIN product p ON lr.product_id = p.product_id
        JOIN stock_in s ON lr.product_id = s.product_id
        WHERE lr.request_id = :request_id
    """, {"request_id": request_id})
    batches = cursor.fetchall()

    # Fetch location_id and other details from lab_request_header based on request_id
    cursor.execute("""
        SELECT lh.request_id, lh.tanggal_request, lh.user_id , u.user_name, lh.location_id, l.location_name
        FROM lab_request_header lh
        JOIN location l ON lh.location_id = l.location_id
        JOIN USER_TABLE u ON lh.user_id = u.user_id
        WHERE lh.request_id = :request_id
    """, {"request_id": request_id})
    header_data = cursor.fetchone()

    # Prepare location and additional details
    if header_data:
        header = {
            "request_id": header_data[0],
            "tanggal_request": header_data[1].strftime('%Y-%m-%d'),  # Format date
            "user_id": header_data[2],
            "user_name": header_data[3],
            "location_id": header_data[4],
            "location_name": header_data[5]
        }
    else:
        # Define location as an empty dictionary or None to avoid undefined error
        location = {
            "request_id": None,
            "tanggal_request": None,
            "user_id": None,
            "location_id": None,
            "location_name": "Unknown"  # Default value if not found
        }

    cursor.close()

    if request.method == 'POST':
        # Handle form submission for stock out
        batch_no = request.form.get('batch_no')
        stock_out_date = request.form.get('stock_out_date')
        remarks = request.form.get('remarks') or None
        update_by = 'RTS'
        update_on = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Iterate through each product_id and qty from lab_request_detail
        cursor = conn.cursor()
        for detail in lab_request_details:
            product_id = detail['product_id']
            stock_out_qty = detail['request_qty']

            # Get the next value from the sequence for ID_STOCK_OUT
            cursor.execute("SELECT stock_out_seq.NEXTVAL FROM dual")
            sequence_value = cursor.fetchone()[0]

            # Format ID_STOCK_OUT
            id_stock_out = f"SO24{sequence_value:08d}"  # Format SO24000001

            # Insert data into stock_out table
            cursor.execute("""
                INSERT INTO stock_out (
                    id_stock_out, product_id, batch_no, stock_out_date, stock_out_qty, location_id, remark, update_by, update_on
                ) VALUES (
                    :id_stock_out, :product_id, :batch_no, TO_DATE(:stock_out_date, 'YYYY-MM-DD'), :stock_out_qty, :location_id, :remarks, :update_by, TO_DATE(:update_on, 'YYYY-MM-DD HH24:MI:SS')
                )
            """, {
                "id_stock_out": id_stock_out,
                "product_id": product_id,
                "batch_no": batch_no,
                "stock_out_date": stock_out_date,
                "stock_out_qty": stock_out_qty,
                "location_id": location['location_id'],
                "remarks": remarks,
                "update_by": update_by,
                "update_on": update_on
            })

        # Commit the transaction
        conn.commit()
        cursor.close()

        return redirect(url_for('inventory_data'))

    return render_template('stock_out.html', 
                           lab_request_details=lab_request_details,
                           request_id=request_id,
                           batches=batches,
                           header=header)

@app.route('/save_stock_out', methods=['POST'])
def save_stock_out():
    data = request.json
    print(data)  # Log data yang diterima

    location_id = data.get('location_id')
    added_items = data.get('added_items')
    request_id = data.get('request_id')  # Ambil request_id dari data

    try:
        cursor = conn.cursor()

        # Ambil sequence untuk ID_STOCK_OUT
        sequence_number = cursor.execute("SELECT stock_out_seq.NEXTVAL FROM dual").fetchone()[0]

        # Format ID_STOCK_OUT
        current_date = datetime.now()
        formatted_id = f"SO{current_date.strftime('%y%m%d')}{str(sequence_number).zfill(3)}"

        # Simpan ke stock_out_header
        cursor.execute('''
            INSERT INTO stock_out_header (ID_STOCK_OUT, STOCK_OUT_DATE, LOCATION_ID, UPDATE_BY, UPDATE_ON, REQUEST_ID)
            VALUES (:id_stock_out, SYSDATE, :location_id, 'ZDN', SYSDATE, :request_id)
        ''', {
            'id_stock_out': formatted_id,
            'location_id': location_id,
            'request_id': request_id  # Menyimpan request_id
        })

        # Simpan ke stock_out untuk setiap item yang ditambahkan
        for item in added_items:
            cursor.execute('''
                INSERT INTO stock_out (ID_STOCK_OUT, PRODUCT_ID, BATCH_NO, STOCK_OUT_QTY, UPDATE_BY, UPDATE_ON)
                VALUES (:stock_out_id, :product_id, :batch_no, :stock_out_qty, 'ZDN', SYSDATE)
            ''', {
                'stock_out_id': formatted_id,  # Menggunakan ID_STOCK_OUT yang sama
                'product_id': item['product_id'],
                'batch_no': item['batch_no'],
                'stock_out_qty': item['qty']
            })

            # Update lab_request_detail untuk kolom id_stock_out
            cursor.execute('''
                UPDATE lab_request_detail
                SET ID_STOCK_OUT = :stock_out_id
                WHERE REQUEST_ID = :request_id AND PRODUCT_ID = :product_id
            ''', {
                'stock_out_id': formatted_id,
                'request_id': request_id,
                'product_id': item['product_id']
            })

        # Commit dan tutup koneksi
        conn.commit()
        cursor.close()

        return jsonify({'message': 'Data saved successfully', 'redirect_url': url_for('inventory_data')}), 201
        
    except Exception as e:
        print("Error:", e)  # Log kesalahan
        return jsonify({'error': str(e)}), 500


@app.route('/fetch_item_data/<string:product_id>', methods=['GET'])
def fetch_item_data(product_id):
    cursor = conn.cursor()

    # Execute the SQL query to fetch item data
    cursor.execute("""
        WITH stock_out_agg AS (
            SELECT 
                product_id,
                batch_no,
                SUM(stock_out_qty) AS total_stock_out
            FROM 
                stock_out
            GROUP BY 
                product_id,
                batch_no
        ),
        stock_in_agg AS (
            SELECT 
                product_id, 
                batch_no,
                stock_expired,
                SUM(stock_in_qty) AS total_stock_in
            FROM 
                stock_in
            GROUP BY 
                product_id,
                batch_no,
                stock_expired
        )
        SELECT 
            p.product_id, 
            p.product_name,
            COALESCE(si.batch_no, so.batch_no) AS batch_no,
            si.stock_expired,
            COALESCE(si.total_stock_in, 0) AS stock_in,
            COALESCE(so.total_stock_out, 0) AS stock_out,
            COALESCE(si.total_stock_in, 0) - COALESCE(so.total_stock_out, 0) AS current_stock
        FROM 
            product p
        LEFT JOIN 
            supplier s ON p.supplier_id = s.supplier_id
        LEFT JOIN 
            manufacture m ON p.manu_id = m.manu_id
        LEFT JOIN 
            stock_in_agg si ON p.product_id = si.product_id
        LEFT JOIN 
            stock_out_agg so ON p.product_id = so.product_id AND si.batch_no = so.batch_no
        WHERE 
            p.product_id = :product_id and
            COALESCE(si.total_stock_in, 0) - COALESCE(so.total_stock_out, 0) > 0
        ORDER BY 
            p.product_name ASC, 
            si.stock_expired ASC,
            COALESCE(si.batch_no, so.batch_no) ASC
    """, {"product_id": product_id})

    # Fetch the results
    items = cursor.fetchall()
    cursor.close()

    # Prepare the data for JSON response
    result = []
    for row in items:
        result.append({
            "product_id": row[0],
            "product_name": row[1],
            "batch_no": row[2],
            "stock_expired": row[3].strftime('%Y-%m-%d') if row[3] else None,
            "stock_in": row[4],
            "stock_out": row[5],
            "current_stock": row[6]
        })

    return jsonify(result)                

@app.route('/get_product_type/<product_id>')
def get_product_type(product_id):
    cursor = conn.cursor()
    cursor.execute("SELECT type_id FROM product WHERE product_id = :product_id", {"product_id": product_id})
    type_id = cursor.fetchone()
    cursor.close()
    return jsonify({"type_id": type_id[0] if type_id else None})

@app.route('/get_batches/<product_id>', methods=['GET'])
def get_batches(product_id):
    cursor = conn.cursor()
    cursor.execute("SELECT batch_no FROM stock_in WHERE product_id = :product_id", {"product_id": product_id})
    batches = cursor.fetchall()
    cursor.close()
    return jsonify([batch[0] for batch in batches])

#Route near expired
@app.route('/near_expired')
def near_expired():
    cursor = conn.cursor()

    query = """
        SELECT 
            si.product_id, 
            p.product_name, 
            si.batch_no,
            TO_CHAR(si.stock_expired, 'YYYY-MM-DD') AS stock_expired,
            COALESCE(SUM(si.stock_in_qty), 0) - COALESCE(SUM(so.stock_out_qty), 0) AS current_stock
        FROM 
            product p
        LEFT JOIN 
            stock_in si ON p.product_id = si.product_id
        LEFT JOIN 
            stock_out so ON p.product_id = so.product_id AND si.batch_no = so.batch_no
        WHERE 
            si.stock_expired < ADD_MONTHS(SYSDATE, 2)
        GROUP BY 
            si.product_id, p.product_name, si.batch_no, si.stock_expired
    """
    cursor.execute(query)
    rows = cursor.fetchall()

    # Map rows to a list of dictionaries
    inventory = [
        {
            "product_id": row[0],
            "product_name": row[1],
            "batch_no": row[2],
            "stock_expired": row[3],
            "current_stock": row[4]
        }
        for row in rows
    ]
    cursor.close()

    # Render template with data
    return render_template('near_expired.html', inventory=inventory)

@app.route('/stock_request', methods=['GET', 'POST'])
def stock_request():
    cursor = conn.cursor()

    # Dropdown untuk produk
    cursor.execute("SELECT product_id, product_name FROM product")
    products = cursor.fetchall()

    # Dropdown untuk lokasi (lab/gudang)
    cursor.execute("SELECT location_id, location_name FROM location")
    locations = cursor.fetchall()

    cursor.close()

    if request.method == 'POST':
        location_id = request.form.get('location_id')  # Lokasi (lab/gudang)
        user_id = 'LAB_USER'  # Nama pengguna yang melakukan permintaan
        tanggal_request = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        remark = request.form.get('remarks') or None  # Catatan tambahan

        # Ambil nilai dari sequence
        cursor = conn.cursor()
        cursor.execute("SELECT lab_request_seq.NEXTVAL FROM dual")
        sequence_value = cursor.fetchone()[0]
        cursor.close()

        # Format ID permintaan
        request_id = f"REQ24{sequence_value:08d}"  # Format REQ24000001

        # Membuka koneksi dan cursor untuk INSERT ke header
        cursor = conn.cursor()

        # Simpan data ke tabel `lab_request_header`
        cursor.execute("""
            INSERT INTO lab_request_header (request_id, tanggal_request, user_id, location_id, remark)
            VALUES (:request_id, TO_DATE(:tanggal_request, 'YYYY-MM-DD HH24:MI:SS'), :user_id, :location_id, :remark)
        """, {
            "request_id": request_id,
            "tanggal_request": tanggal_request,
            "user_id": user_id,
            "location_id": location_id,
            "remark": remark
        })

        # Ambil data produk dari form untuk tabel detail
        products = request.form.getlist('product_id')
        quantities = request.form.getlist('request_qty')

        for product_id, request_qty in zip(products, quantities):
            cursor.execute("""
                INSERT INTO lab_request_detail (request_id, product_id, request_qty)
                VALUES (:request_id, :product_id, :request_qty)
            """, {
                "request_id": request_id,
                "product_id": product_id,
                "request_qty": request_qty
            })

        conn.commit()
        cursor.close()

        # Redirect ke halaman daftar permintaan stok
        return redirect(url_for('stock_request_list'))

    return render_template('stock_request.html', products=products, locations=locations)

@app.route('/stock_request_list', methods=['GET'])
def stock_request_list():
    cursor = conn.cursor()

    # Query untuk mendapatkan daftar permintaan stok (gabungan header dan detail)
    cursor.execute("""
        SELECT 
            h.request_id,
            d.product_id,
            p.product_name,
            l.location_name,
            d.request_qty,
            h.remark,
            h.tanggal_request
        FROM 
            lab_request_header h
        JOIN lab_request_detail d ON h.request_id = d.request_id
        JOIN product p ON d.product_id = p.product_id
        JOIN location l ON h.location_id = l.location_id
        ORDER BY h.tanggal_request DESC
    """)
    requests = [{
        "request_id": row[0],
        "product_id": row[1],
        "product_name": row[2],
        "location_name": row[3],
        "request_qty": row[4],
        "remark": row[5],
        "tanggal_request": row[6]
    } for row in cursor.fetchall()]

    cursor.close()
    return render_template('stock_request_list.html', requests=requests)

'''
@app.route('/stock_request', methods=['GET', 'POST'])
def stock_request():
    cursor = conn.cursor()

    # Dropdown untuk produk
    cursor.execute("SELECT product_id, product_name FROM product")
    products = cursor.fetchall()

    # Dropdown untuk lokasi (lab/gudang)
    cursor.execute("SELECT location_id, location_name FROM location")
    locations = cursor.fetchall()

    cursor.close()

    if request.method == 'POST':
        product_id = request.form.get('product_id')  # Ambil product_id dari form
        location_id = request.form.get('location_id')  # Ambil lokasi (lab/gudang)
        request_qty = request.form.get('request_qty')  # Kuantitas yang diminta
        remarks = request.form.get('remarks') or None  # Catatan tambahan
        update_by = 'LAB_USER'  # Nama pengguna yang melakukan permintaan
        update_on = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Ambil nilai dari sequence
        cursor = conn.cursor()
        cursor.execute("SELECT stock_request_seq.NEXTVAL FROM dual")
        sequence_value = cursor.fetchone()[0]
        cursor.close()

        # Format ID permintaan stok
        request_id = f"REQ24{sequence_value:08d}"  # Format REQ24000001

        # Membuka koneksi dan cursor untuk INSERT
        cursor = conn.cursor()

        # Simpan data ke tabel `stock_request`
        cursor.execute("""
            INSERT INTO stock_request (request_id, product_id, location_id, request_qty, remark, update_by, update_on)
            VALUES (:request_id, :product_id, :location_id, :request_qty, :remarks, :update_by, TO_DATE(:update_on, 'YYYY-MM-DD HH24:MI:SS'))
        """, {
            "request_id": request_id,
            "product_id": product_id,
            "location_id": location_id,
            "request_qty": request_qty,
            "remarks": remarks,
            "update_by": update_by,
            "update_on": update_on
        })

        conn.commit()
        cursor.close()

        # Redirect ke halaman daftar permintaan stok
        return redirect(url_for('stock_request_list'))

    return render_template('stock_request.html', products=products, locations=locations)

@app.route('/stock_request_list', methods=['GET'])
def stock_request_list():
    cursor = conn.cursor()

    # Query untuk mendapatkan daftar permintaan stok
    cursor.execute("""
        SELECT 
            sr.request_id,
            p.product_name,
            l.location_name,
            sr.request_qty,
            sr.remark,
            sr.update_on
        FROM 
            stock_request sr
        JOIN product p ON sr.product_id = p.product_id
        JOIN location l ON sr.location_id = l.location_id
        ORDER BY sr.update_on DESC
    """)
    requests = [{
        "request_id": row[0],
        "product_name": row[1],
        "location_name": row[2],
        "request_qty": row[3],
        "remark": row[4],
        "update_on": row[5]
    } for row in cursor.fetchall()]

    cursor.close()
    return render_template('stock_request_list.html', requests=requests)
'''
'''
# Route Master Inventory Detail-----------------------------------------------------------------------------------------------------------------
@app.route('/inventory_data_detail/<string:product_id>')
def inventory_data_detail(product_id):
    cursor = conn.cursor()

    base_query = """
        WITH stock_out_agg AS (
            SELECT 
                product_id,
                batch_no,
                SUM(stock_out_qty) AS total_stock_out
            FROM 
                stock_out
            GROUP BY 
                product_id,
                batch_no
        ),
        stock_in_agg AS (
            SELECT 
                product_id, 
                batch_no,
                SUM(stock_in_qty) AS total_stock_in
            FROM 
                stock_in
            GROUP BY 
                product_id,
                batch_no
        )
        SELECT 
            p.product_id, 
            p.product_name,
            COALESCE(si.batch_no, so.batch_no) AS batch_no,
            s.supp_name, 
            m.manu_name,
            COALESCE(si.total_stock_in, 0) AS stock_in,
            COALESCE(so.total_stock_out, 0) AS stock_out,
            COALESCE(si.total_stock_in, 0) - COALESCE(so.total_stock_out, 0) AS current_stock
        FROM 
            product p
        LEFT JOIN 
            supplier s ON p.supplier_id = s.supplier_id
        LEFT JOIN 
            manufacture m ON p.manu_id = m.manu_id
        LEFT JOIN 
            stock_in_agg si ON p.product_id = si.product_id
        LEFT JOIN 
            stock_out_agg so ON p.product_id = so.product_id AND si.batch_no = so.batch_no
        WHERE 
            p.product_id = :product_id
        ORDER BY 
            p.product_name ASC, 
            COALESCE(si.batch_no, so.batch_no) ASC   

    """

    # Execute the query without any search condition
    cursor.execute(base_query, {"product_id": product_id})

    # Fetch all rows from the executed query
    rows = cursor.fetchall()

    

    # Debugging: Log the number of results
    # print(f"Number of rows returned: {len(rows)}")  # Log the number of rows returned

    # Create a list of dictionaries from the fetched rows
    inventorys = [{
        "product_id": row[0], 
        "product_name": row[1], 
        "batch_no": row[2],  # Include batch_no in the inventory dictionary
        "supp_name": row[3], 
        "manu_name": row[4],
        "stock_in": row[5],
        "stock_out": row[6],
        "current_stock": row[7]
    } for row in rows]
    
    cursor.close()
    print(inventorys)

    return render_template('inventory_data_detail.html', inventorys=inventorys)
'''

@app.route('/transfer_item', methods=['GET', 'POST'])
def transfer_item():
    if request.method == 'POST':
        data = request.get_json()
        location_id = data['location_id']
        added_items = data['added_items']

        # Simpan transfer detail ke database
        for item in added_items:
            transfer_detail = TransferDetail(
                transfer_id=1,  # Ganti dengan ID transfer yang sesuai
                product_id=item['product_id'],
                loc_from='Current Warehouse',  # Ganti dengan lokasi asal
                loc_to=location_id,
                batch_no=item['batch_no'],
                transfer_qty=item['qty']
            )
            db.session.add(transfer_detail)

        db.session.commit()
        return jsonify({'message': 'Transfer successful!', 'redirect_url': '/'}), 200

    # Jika GET, tampilkan halaman transfer
    return render_template('transfer.html')


# Route Master Inventory Detail-----------------------------------------------------------------------------------------------------------------
@app.route('/inventory_data_detail/<string:product_id>')
def inventory_data_detail(product_id):
    cursor = conn.cursor()

    base_query = """
        WITH stock_out_agg AS (
            SELECT 
                product_id,
                batch_no,
                SUM(stock_out_qty) AS total_stock_out
            FROM 
                stock_out
            GROUP BY 
                product_id,
                batch_no
        ),
        stock_in_agg AS (
            SELECT 
                product_id, 
                batch_no,
                SUM(stock_in_qty) AS total_stock_in
            FROM 
                stock_in
            GROUP BY 
                product_id,
                batch_no
        )
        SELECT 
            p.product_id, 
            p.product_name,
            COALESCE(si.batch_no, so.batch_no) AS batch_no,
            s.supp_name, 
            m.manu_name,
            COALESCE(si.total_stock_in, 0) AS stock_in,
            COALESCE(so.total_stock_out, 0) AS stock_out,
            COALESCE(si.total_stock_in, 0) - COALESCE(so.total_stock_out, 0) AS current_stock
        FROM 
            product p
        LEFT JOIN 
            supplier s ON p.supplier_id = s.supplier_id
        LEFT JOIN 
            manufacture m ON p.manu_id = m.manu_id
        LEFT JOIN 
            stock_in_agg si ON p.product_id = si.product_id
        LEFT JOIN 
            stock_out_agg so ON p.product_id = so.product_id AND si.batch_no = so.batch_no
        WHERE 
            p.product_id = :product_id
        ORDER BY 
            p.product_name ASC, 
            COALESCE(si.batch_no, so.batch_no) ASC   

    """

    # Execute the query without any search condition
    cursor.execute(base_query, {"product_id": product_id})

    # Fetch all rows from the executed query
    rows = cursor.fetchall()

    

    # Debugging: Log the number of results
    # print(f"Number of rows returned: {len(rows)}")  # Log the number of rows returned

    # Create a list of dictionaries from the fetched rows
    inventorys = [{
        "product_id": row[0], 
        "product_name": row[1], 
        "batch_no": row[2],  # Include batch_no in the inventory dictionary
        "supp_name": row[3], 
        "manu_name": row[4],
        "stock_in": row[5],
        "stock_out": row[6],
        "current_stock": row[7]
    } for row in rows]
    
    cursor.close()
    print(inventorys)

    return render_template('inventory_data_detail.html', inventorys=inventorys)
                           
@app.route('/reagent_use', methods=['GET', 'POST'])
@login_required
def reagent_use():
    # Query untuk mengambil data penggunaan reagen
    cursor = conn.cursor()
    query_reagent_use = """
        SELECT 
            r.reagent_id, 
            r.reagent_name, 
            ru.use_qty, 
            TO_CHAR(ru.use_date, 'YYYY-MM-DD') AS use_date
        FROM 
            reagent r
        LEFT JOIN 
            reagent_use ru ON r.reagent_id = ru.reagent_id
        WHERE 
            ru.use_date IS NOT NULL
    """
    cursor.execute(query_reagent_use)
    rows_reagent_use = cursor.fetchall()

    reagent_uses = [
        {
            "reagent_id": row[0],
            "reagent_name": row[1],
            "use_qty": row[2],
            "use_date": row[3]
        }
        for row in rows_reagent_use
    ]
    cursor.close()

    # Mendapatkan nama pengguna dari sesi
    username = session.get('user_name', 'User')

    return render_template('reagent_use.html', reagent_uses=reagent_uses, username=username)


@app.route('/report')
def report():
    cursor = conn.cursor()

    # Ambil parameter filter dari query string
    product_name = request.args.get('product_name', '').lower()
    supplier_name = request.args.get('supplier_name', '').lower()
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    # Base query
    base_query = """
        WITH stock_out_agg AS (
            SELECT 
                product_id, 
                SUM(stock_out_qty) AS total_stock_out
            FROM 
                stock_out
            GROUP BY 
                product_id
        ),
        stock_in_agg AS (
            SELECT 
                product_id, 
                SUM(stock_in_qty) AS total_stock_in
            FROM 
                stock_in
            GROUP BY 
                product_id
        )
        SELECT 
            p.product_id, 
            p.product_name, 
            s.supp_name, 
            m.manu_name,
            COALESCE(si.total_stock_in, 0) AS stock_in,
            COALESCE(so.total_stock_out, 0) AS stock_out,
            COALESCE(si.total_stock_in, 0) - COALESCE(so.total_stock_out, 0) AS current_stock,
            p.safety_level
        FROM 
            product p
        LEFT JOIN 
            supplier s ON p.supplier_id = s.supplier_id
        LEFT JOIN 
            manufacture m ON p.manu_id = m.manu_id
        LEFT JOIN 
            stock_in_agg si ON p.product_id = si.product_id
        LEFT JOIN 
            stock_out_agg so ON p.product_id = so.product_id
    """

    # Tambahkan kondisi berdasarkan filter
    conditions = []
    params = {}

    if product_name:
        conditions.append("LOWER(p.product_name) LIKE :product_name")
        params["product_name"] = f"%{product_name}%"

    if supplier_name:
        conditions.append("LOWER(s.supp_name) LIKE :supplier_name")
        params["supplier_name"] = f"%{supplier_name}%"

    if date_from:
        conditions.append("EXISTS (SELECT 1 FROM stock_in WHERE stock_in.product_id = p.product_id AND stock_in_date >= TO_DATE(:date_from, 'YYYY-MM-DD'))")
        params["date_from"] = date_from

    if date_to:
        conditions.append("EXISTS (SELECT 1 FROM stock_in WHERE stock_in.product_id = p.product_id AND stock_in_date <= TO_DATE(:date_to, 'YYYY-MM-DD'))")
        params["date_to"] = date_to

    # Gabungkan kondisi ke query
    if conditions:
        base_query += " WHERE " + " AND ".join(conditions)

    base_query += " ORDER BY p.product_name ASC"

    # Eksekusi query
    cursor.execute(base_query, params)
    inventorys = [{
        "product_id": row[0],
        "product_name": row[1],
        "supp_name": row[2],
        "manu_name": row[3],
        "stock_in": row[4],
        "stock_out": row[5],
        "current_stock": row[6],
        "safety_level": row[7]
    } for row in cursor.fetchall()]
    cursor.close()

    return render_template('report.html', inventorys=inventorys)

@app.route('/download_report', methods=['GET'])
def download_report():
    cursor = conn.cursor()

    # Ambil parameter filter dari query string
    product_name = request.args.get('product_name', '').lower()
    supplier_name = request.args.get('supplier_name', '').lower()
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    # Base query
    base_query = """
        WITH stock_out_agg AS (
            SELECT 
                product_id, 
                SUM(stock_out_qty) AS total_stock_out
            FROM 
                stock_out
            GROUP BY 
                product_id
        ),
        stock_in_agg AS (
            SELECT 
                product_id, 
                SUM(stock_in_qty) AS total_stock_in
            FROM 
                stock_in
            GROUP BY 
                product_id
        )
        SELECT 
            p.product_id, 
            p.product_name, 
            s.supp_name, 
            m.manu_name,
            COALESCE(si.total_stock_in, 0) AS stock_in,
            COALESCE(so.total_stock_out, 0) AS stock_out,
            COALESCE(si.total_stock_in, 0) - COALESCE(so.total_stock_out, 0) AS current_stock,
            p.safety_level
        FROM 
            product p
        LEFT JOIN 
            supplier s ON p.supplier_id = s.supplier_id
        LEFT JOIN 
            manufacture m ON p.manu_id = m.manu_id
        LEFT JOIN 
            stock_in_agg si ON p.product_id = si.product_id
        LEFT JOIN 
            stock_out_agg so ON p.product_id = so.product_id
    """

    # Tambahkan kondisi berdasarkan filter
    conditions = []
    params = {}

    if product_name:
        conditions.append("LOWER(p.product_name) LIKE :product_name")
        params["product_name"] = f"%{product_name}%"

    if supplier_name:
        conditions.append("LOWER(s.supp_name) LIKE :supplier_name")
        params["supplier_name"] = f"%{supplier_name}%"

    if date_from:
        conditions.append("EXISTS (SELECT 1 FROM stock_in WHERE stock_in.product_id = p.product_id AND stock_in_date >= TO_DATE(:date_from, 'YYYY-MM-DD'))")
        params["date_from"] = date_from

    if date_to:
        conditions.append("EXISTS (SELECT 1 FROM stock_in WHERE stock_in.product_id = p.product_id AND stock_in_date <= TO_DATE(:date_to, 'YYYY-MM-DD'))")
        params["date_to"] = date_to

    # Gabungkan kondisi ke query
    if conditions:
        base_query += " WHERE " + " AND ".join(conditions)

    base_query += " ORDER BY p.product_name ASC"

    # Eksekusi query
    cursor.execute(base_query, params)
    inventorys = [{
        "product_id": row[0],
        "product_name": row[1],
        "supp_name": row[2],
        "manu_name": row[3],
        "stock_in": row[4],
        "stock_out": row[5],
        "current_stock": row[6],
        "safety_level": row[7]
    } for row in cursor.fetchall()]
    cursor.close()

    # Simpan data ke file Excel
    df = pd.DataFrame(inventorys)
    file_path = 'inventory_report.xlsx'
    df.to_excel(file_path, index=False, engine='openpyxl')

    return send_file(file_path, as_attachment=True)


if __name__ == "__main__":
    app.run(host='127.0.0.1', port=5017, debug=True)
