
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from banco import connect, create_database
import sqlite3

app = Flask(__name__)
app.secret_key = "change-this-secret-key"


# NGO Registration
@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form["name"]
        address = request.form["address"]
        contact = request.form["contact"]
        email = request.form["email"]
        password = request.form["password"]

        connection = connect()

        try:
            # Register the NGO
            cursor = connection.execute("""
                INSERT INTO ngos (name, address, contact)
                VALUES (?, ?, ?)
            """, (name, address, contact))

            # Get the ID of the registered NGO
            ngo_id = cursor.lastrowid

            # Hash the password
            password_hash = generate_password_hash(password)

            # Create the NGO login credentials
            connection.execute("""
                INSERT INTO ngo_access
                (ngo_id, email, password)
                VALUES (?, ?, ?)
            """, (ngo_id, email, password_hash))

            connection.commit()

            flash("NGO successfully registered!")
            return redirect(url_for("login"))

        except sqlite3.IntegrityError:
            connection.rollback()
            flash("This email is already registered.")

        finally:
            connection.close()

    return render_template("cadastro_ong.html")


# NGO Login
@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form["email"]
        password = request.form["password"]

        connection = connect()

        ngo = connection.execute("""
            SELECT ngo_access.ngo_id,
                   ngo_access.password,
                   ngos.name
            FROM ngo_access
            JOIN ngos ON ngo_access.ngo_id = ngos.id
            WHERE ngo_access.email = ?
        """, (email,)).fetchone()

        connection.close()

        if ngo and check_password_hash(ngo["password"], password):

            session["ngo_id"] = ngo["ngo_id"]
            session["ngo_name"] = ngo["name"]

            return redirect(url_for("dashboard"))

        flash("Incorrect email or password.")

    return render_template("login.html")


# NGO Dashboard
@app.route("/dashboard")
def dashboard():

    if "ngo_id" not in session:
        return redirect(url_for("login"))

    connection = connect()

    # Retrieve donation categories
    categories = connection.execute("""
        SELECT id, name
        FROM donation_types
    """).fetchall()

    # Retrieve requests from the logged-in NGO
    requests_list = connection.execute("""
        SELECT
            requests.id,
            donation_types.name AS type,
            requests.description,
            requests.quantity,
            requests.priority,
            requests.status
        FROM requests
        JOIN donation_types
        ON requests.type_id = donation_types.id
        WHERE requests.ngo_id = ?
        ORDER BY requests.id DESC
    """, (session["ngo_id"],)).fetchall()

    connection.close()

    return render_template(
        "painel_ong.html",
        ngo_name=session["ngo_name"],
        categories=categories,
        requests=requests_list
    )


# Create a Donation Request
@app.route("/create_request", methods=["POST"])
def create_request():

    if "ngo_id" not in session:
        return redirect(url_for("login"))

    type_id = request.form["type_id"]
    description = request.form["description"]
    quantity = request.form["quantity"]
    priority = request.form["priority"]

    connection = connect()

    connection.execute("""
        INSERT INTO requests
        (ngo_id, type_id, description, quantity, priority)
        VALUES (?, ?, ?, ?, ?)
    """, (
        session["ngo_id"],
        type_id,
        description,
        quantity,
        priority
    ))

    connection.commit()
    connection.close()

    flash("Donation request successfully created!")

    return redirect(url_for("dashboard"))


# Log Out
@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))


if __name__ == "__main__":
    create_database()
    app.run(debug=True)

