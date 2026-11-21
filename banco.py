
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

    # Usuários que realizam as doações
    conexao.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            senha TEXT NOT NULL
        )
    """)

    # Instituições que precisam de ajuda
    conexao.execute("""
        CREATE TABLE IF NOT EXISTS instituicoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            endereco TEXT,
            contato TEXT
        )
    """)

    # Pedidos de doação das instituições
    conexao.execute("""
        CREATE TABLE IF NOT EXISTS necessidades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instituicao_id INTEGER NOT NULL,
            categoria TEXT NOT NULL,
            quantidade INTEGER NOT NULL,
            quantidade_atendida INTEGER DEFAULT 0,
            prioridade TEXT NOT NULL,
            FOREIGN KEY (instituicao_id)
                REFERENCES instituicoes(id)
        )
    """)

    # Doações relacionadas a um pedido específico
    conexao.execute("""
        CREATE TABLE IF NOT EXISTS doacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            necessidade_id INTEGER NOT NULL,
            quantidade INTEGER NOT NULL,
            status TEXT DEFAULT 'Pendente',

            FOREIGN KEY (usuario_id)
                REFERENCES usuarios(id),

            FOREIGN KEY (necessidade_id)
                REFERENCES necessidades(id)
        )
    """)

    conexao.commit()
    conexao.close()

    print("Banco de dados criado com sucesso!")


if __name__ == "__main__":
    criar_banco()
