
import sqlite3

# Connect to the database
def connect():
    connection = sqlite3.connect("donations.db")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


# Create the database tables
def create_database():
    connection = connect()

    # NGO registration data
    connection.execute("""
        CREATE TABLE IF NOT EXISTS ngos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            address TEXT,
            contact TEXT
        )
    """)

    # NGO login credentials
    connection.execute("""
        CREATE TABLE IF NOT EXISTS ngo_access (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ngo_id INTEGER NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,

            FOREIGN KEY (ngo_id) REFERENCES ngos(id)
        )
    """)

    # Donation types
    connection.execute("""
        CREATE TABLE IF NOT EXISTS donation_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
    """)

    # Donation requests made by NGOs
    connection.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ngo_id INTEGER NOT NULL,
            type_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            priority TEXT NOT NULL,
            status TEXT DEFAULT 'Open',

            FOREIGN KEY (ngo_id) REFERENCES ngos(id),
            FOREIGN KEY (type_id) REFERENCES donation_types(id)
        )
    """)

    # Initial donation categories
    donation_types = [
        ("Food",),
        ("Clothing",),
        ("Hygiene",),
        ("School Supplies",),
        ("Medicine",)
    ]

    connection.executemany(
        "INSERT OR IGNORE INTO donation_types (name) VALUES (?)",
        donation_types
    )

    # Donations offered by users
    connection.execute("""
        CREATE TABLE IF NOT EXISTS donations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            donor_name TEXT NOT NULL,
            contact TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            status TEXT DEFAULT 'Pending',

            FOREIGN KEY (request_id) REFERENCES requests(id)
        )
    """)

    connection.commit()
    connection.close()

    print("Database created successfully!")


if __name__ == "__main__":
    create_database()
