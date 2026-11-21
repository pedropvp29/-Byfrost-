
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from banco import conectar, criar_banco
import sqlite3

app = Flask(__name__)
app.secret_key = "chave-secreta-trocar-depois"


# Cadastro de uma ONG
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
            # Cadastrar a ONG
            cursor = conexao.execute("""
                INSERT INTO ongs (nome, endereco, contato)
                VALUES (?, ?, ?)
            """, (nome, endereco, contato))

            # Descobrir o ID da ONG cadastrada
            ong_id = cursor.lastrowid

            # Proteger a senha
            senha_hash = generate_password_hash(senha)

            # Criar acesso da ONG
            conexao.execute("""
                INSERT INTO acessos_ong
                (ong_id, email, senha)
                VALUES (?, ?, ?)
            """, (ong_id, email, senha_hash))

            conexao.commit()

            flash("ONG cadastrada com sucesso!")
            return redirect(url_for("login"))

        except sqlite3.IntegrityError:
            conexao.rollback()
            flash("Este e-mail já está cadastrado.")

        finally:
            conexao.close()

    return render_template("cadastro_ong.html")


# Login da ONG
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

        flash("E-mail ou senha incorretos.")

    return render_template("login.html")


# Painel exclusivo da ONG
@app.route("/painel")
def painel():

    if "ong_id" not in session:
        return redirect(url_for("login"))

    return render_template(
        "painel_ong.html",
        ong_nome=session["ong_nome"]
    )


# Sair da conta
@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))


if __name__ == "__main__":
    criar_banco()
    app.run(debug=True)
