import mysql.connector
import random

db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="123456",
    database="blood_bank_db"
)
cursor = db.cursor()

first_names = ["Arif", "Sajid", "Nila", "Sumon", "Anika", "Tanvir", "Rashed", "Mitu", "Fahim", "Jannat"]
last_names = ["Hossain", "Khan", "Ahmed", "Islam", "Akter", "Uddin", "Chowdhury", "Rahman"]
blood_groups = ["A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"]
cities = ["Dhaka", "Mymensingh", "Chittagong", "Sylhet", "Rajshahi", "Khulna", "Barisal", "Cumilla"]

for i in range(500):
    name = f"{random.choice(first_names)} {random.choice(last_names)}"
    email = f"donor_{i}_{random.randint(1000, 9999)}@gmail.com"
    password = "hashed_password"
    bg = random.choice(blood_groups)
    city = random.choice(cities)
    phone = f"01{random.randint(3, 9)}{random.randint(10000000, 99999999)}"

    query = "INSERT INTO user (name, email, password, blood_group, city, phone) VALUES (%s, %s, %s, %s, %s, %s)"
    values = (name, email, password, bg, city, phone)
    cursor.execute(query, values)

db.commit()
cursor.close()
db.close()
print("500 Donors Added Successfully")