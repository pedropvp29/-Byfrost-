
import sqlite3

# Connect to the database
def connect():
    connection = sqlite3.connect("doacoes.db")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


# Create the database tables
def create_database():
    connection = connect()

    # NGO registration data
    connection.execute("""
        CREATE TABLE IF NOT EXISTS ongs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            endereco TEXT,
            contato TEXT
        )
    """)

    # NGO login credentials
    connection.execute("""
        CREATE TABLE IF NOT EXISTS acessos_ong (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ong_id INTEGER NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            senha TEXT NOT NULL,

            FOREIGN KEY (ong_id) REFERENCES ongs(id)
        )
    """)

    # Donation types
    connection.execute("""
        CREATE TABLE IF NOT EXISTS tipos_doacao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE
        )
    """)

    # Donation requests made by NGOs
    connection.execute("""
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

    # Initial donation categories
    donation_types = [
        ("Alimentos",),
        ("Roupas",),
        ("Higiene",),
        ("Material escolar",),
        ("Medicamentos",)
    ]

    connection.executemany(
        "INSERT OR IGNORE INTO tipos_doacao (nome) VALUES (?)",
        donation_types
    )

    # Donations offered by users
    connection.execute("""
        CREATE TABLE IF NOT EXISTS doacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pedido_id INTEGER NOT NULL,
            nome_doador TEXT NOT NULL,
            contato TEXT NOT NULL,
            quantidade INTEGER NOT NULL,
            status TEXT DEFAULT 'Pendente',

            FOREIGN KEY (pedido_id) REFERENCES pedidos(id)
        )
    """)

    connection.commit()
    connection.close()

    print("Database created successfully!")


if __name__ == "__main__":
    create_database()
