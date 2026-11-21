
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from banco import conectar, criar_banco
import sqlite3

app = Flask(__name__)
app.secret_key = "chave-secreta-trocar-depois"


# NGO Registration
@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():

    if request.method == "POST":

        nome = request.form["nome"]
        endereco = request.form["endereco"]
        contato = request.form["contato"]
        email = request.form["email"]
        senha = request.form["senha"]

        conexao = conectar()

        try:
            # Register the NGO
            cursor = conexao.execute("""
                INSERT INTO ongs (nome, endereco, contato)
                VALUES (?, ?, ?)
            """, (nome, endereco, contato))

            # Get the ID of the registered NGO
            ong_id = cursor.lastrowid

            # Hash the password
            senha_hash = generate_password_hash(senha)

            # Create the NGO login credentials
            conexao.execute("""
                INSERT INTO acessos_ong
                (ong_id, email, senha)
                VALUES (?, ?, ?)
            """, (ong_id, email, senha_hash))

            conexao.commit()

            flash("NGO successfully registered!")
            return redirect(url_for("login"))

        except sqlite3.IntegrityError:
            conexao.rollback()
            flash("This email is already registered.")

        finally:
            conexao.close()

    return render_template("cadastro_ong.html")


# NGO Login
@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form["email"]
        senha = request.form["senha"]

        conexao = conectar()

        ong = conexao.execute("""
            SELECT acessos_ong.ong_id,
                   acessos_ong.senha,
                   ongs.nome
            FROM acessos_ong
            JOIN ongs ON acessos_ong.ong_id = ongs.id
            WHERE acessos_ong.email = ?
        """, (email,)).fetchone()

        conexao.close()

        if ong and check_password_hash(ong["senha"], senha):

            session["ong_id"] = ong["ong_id"]
            session["ong_nome"] = ong["nome"]

            return redirect(url_for("painel"))

        flash("Incorrect email or password.")

    return render_template("login.html")


# NGO Dashboard
@app.route("/painel")
def painel():

    if "ong_id" not in session:
        return redirect(url_for("login"))

    conexao = conectar()

    # Retrieve donation categories
    categorias = conexao.execute("""
        SELECT id, nome
        FROM tipos_doacao
    """).fetchall()

    # Retrieve requests from the logged-in NGO
    pedidos = conexao.execute("""
        SELECT
            pedidos.id,
            tipos_doacao.nome AS tipo,
            pedidos.descricao,
            pedidos.quantidade,
            pedidos.prioridade,
            pedidos.status
        FROM pedidos
        JOIN tipos_doacao
        ON pedidos.tipo_id = tipos_doacao.id
        WHERE pedidos.ong_id = ?
        ORDER BY pedidos.id DESC
    """, (session["ong_id"],)).fetchall()

    conexao.close()

    return render_template(
        "painel_ong.html",
        ong_nome=session["ong_nome"],
        categorias=categorias,
        pedidos=pedidos
    )


# Create a Donation Request
@app.route("/cadastrar_pedido", methods=["POST"])
def cadastrar_pedido():

    if "ong_id" not in session:
        return redirect(url_for("login"))

    tipo_id = request.form["tipo_id"]
    descricao = request.form["descricao"]
    quantidade = request.form["quantidade"]
    prioridade = request.form["prioridade"]

    conexao = conectar()

    conexao.execute("""
        INSERT INTO pedidos
        (ong_id, tipo_id, descricao, quantidade, prioridade)
        VALUES (?, ?, ?, ?, ?)
    """, (
        session["ong_id"],
        tipo_id,
        descricao,
        quantidade,
        prioridade
    ))

    conexao.commit()
    conexao.close()

    flash("Donation request successfully created!")

    return redirect(url_for("painel"))


# Log Out
@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))


if __name__ == "__main__":
    criar_banco()
    app.run(debug=True)
