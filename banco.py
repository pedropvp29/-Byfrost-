
import sqlite3

# Conectar ao banco de dados
def conectar():
    conexao = sqlite3.connect("doacoes.db")
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA foreign_keys = ON")
    return conexao


# Criar as tabelas
def criar_banco():
    conexao = conectar()

    # Cadastro das ONGs
    conexao.execute("""
        CREATE TABLE IF NOT EXISTS ongs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            endereco TEXT,
            contato TEXT
        )
    """)
    
    # Dados de acesso das ONGs
    conexao.execute("""
        CREATE TABLE IF NOT EXISTS acessos_ong (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ong_id INTEGER NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            senha TEXT NOT NULL,

            FOREIGN KEY (ong_id) REFERENCES ongs(id)
        )
    """)


    # Tipos de doação
    conexao.execute("""
        CREATE TABLE IF NOT EXISTS tipos_doacao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE
        )
    """)

    # Pedidos feitos pelas ONGs
    conexao.execute("""
        CREATE TABLE IF NOT EXISTS pedidos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ong_id INTEGER NOT NULL,
            tipo_id INTEGER NOT NULL,
            descricao TEXT NOT NULL,
            quantidade INTEGER NOT NULL,
            prioridade TEXT NOT NULL,
            status TEXT DEFAULT 'Aberto',

            FOREIGN KEY (ong_id) REFERENCES ongs(id),
            FOREIGN KEY (tipo_id) REFERENCES tipos_doacao(id)
        )
    """)

    # Categorias iniciais
    tipos = [
        ("Alimentos",),
        ("Roupas",),
        ("Higiene",),
        ("Material escolar",),
        ("Medicamentos",)
    ]

    conexao.executemany(
        "INSERT OR IGNORE INTO tipos_doacao (nome) VALUES (?)",
        tipos
    )

    conexao.commit()
    conexao.close()

    print("Banco criado com sucesso!")


if __name__ == "__main__":
    criar_banco()
