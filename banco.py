
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

    # Tabela de usuários
    conexao.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            senha TEXT NOT NULL
        )
    """)

    # Tabela de instituições
    conexao.execute("""
        CREATE TABLE IF NOT EXISTS instituicoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            endereco TEXT,
            contato TEXT
        )
    """)

    # Tabela de necessidades
    conexao.execute("""
        CREATE TABLE IF NOT EXISTS necessidades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instituicao_id INTEGER NOT NULL,
            categoria TEXT NOT NULL,
            quantidade INTEGER NOT NULL,
            prioridade TEXT NOT NULL,
            FOREIGN KEY (instituicao_id)
                REFERENCES instituicoes(id)
        )
    """)

    # Tabela de doações
    conexao.execute("""
        CREATE TABLE IF NOT EXISTS doacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            categoria TEXT NOT NULL,
            quantidade INTEGER NOT NULL,
            destino TEXT,
            status TEXT DEFAULT 'Pendente',
            FOREIGN KEY (usuario_id)
                REFERENCES usuarios(id)
        )
    """)

    conexao.commit()
    conexao.close()

    print("Banco de dados criado com sucesso!")


if __name__ == "__main__":
    criar_banco()
