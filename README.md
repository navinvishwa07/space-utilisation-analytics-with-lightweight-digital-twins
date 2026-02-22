# SIET – Space Infrastructure Exchange Twin

A lightweight digital twin system that models infrastructure usage, predicts availability, and intelligently allocates underutilized spaces to incoming demand.

Built using clean architecture principles and production-grade engineering standards.

---

## 🚀 Overview

Many institutions and public infrastructures (classrooms, labs, auditoriums, seminar halls) remain underutilized during specific time windows.

SIET (Space Infrastructure Exchange Twin) creates a lightweight digital twin that:

- Tracks historical room utilization  
- Predicts future availability patterns  
- Matches external/internal demand with unused capacity  
- Logs allocation decisions transparently  
- Simulates optimization scenarios  

This project is designed for clarity, scalability, and engineering discipline.

---

## 🧠 MVP Features

The Minimum Viable Product includes:

- SQLite-backed digital twin database  
- 10+ rooms with 3 weeks of synthetic booking history  
- Availability prediction logic  
- Constraint-aware matching engine  
- Allocation logging system  
- Modular backend architecture  
- Structured documentation  
- Unit test-ready structure  

No external APIs. Fully local and portable.

---

## 🏗 Architecture

The system follows strict separation of concerns.
'''
backend/
│
├── main.py
├── controllers/
├── services/
├── domain/
├── repository/
├── utils/
└── data/

dashboard/
docs/
tests/
'''

### Layer Responsibilities

- **Controllers** → Orchestrate workflows  
- **Services** → Business logic (prediction, matching, simulation)  
- **Domain** → Core models and constraints  
- **Repository** → Database access layer  
- **Utils** → Logging and configuration  
- **Dashboard** → UI layer  
- **Tests** → Unit validation  

Business logic never directly accesses the database.  
Database access is isolated inside the repository layer.

---

## 🗃 Database Schema

The SQLite database includes:

- Rooms  
- BookingHistory  
- Requests  
- AllocationLogs  

Synthetic historical data is automatically seeded during initialization.

---

## ⚙️ Installation & Setup

### 1. Clone Repository

```bash
git clone https://github.com/navinvishwa07/AMDSlighshot-space-utilisation-analytics-with-lightweight-digital-twins.git
cd AMDSlighshot-space-utilisation-analytics-with-lightweight-digital-twins

2. Create Virtual Environment

Mac/Linux

python3 -m venv venv
source venv/bin/activate

Windows

python -m venv venv
venv\Scripts\activate

3. Install Dependencies

pip install -r requirements.txt

4. Initialize System

python -m backend.main

Expected output:

Database initialized successfully.
Synthetic data seeded successfully.
System ready.

At this point, the digital twin dataset is live locally.

⸻

🧪 Running Tests

pytest

Each service is designed to be independently testable.

⸻

🧩 Engineering Principles
	•	Clean architecture
	•	Strict separation of concerns
	•	No hardcoded values
	•	Structured logging
	•	Defensive error handling
	•	Modular and scalable design
	•	Configuration-driven behavior

The system is designed to withstand senior engineering review.

⸻

📚 Documentation

Detailed project documentation is available inside:
	•	docs/MVP.md
	•	docs/PRD.md
	•	docs/Architecture.md
	•	docs/AI_rules.md
	•	docs/Skills.md
	•	docs/Plan.md

⸻

👥 Team
	•	Navin Vishwa
	•	Dhiyanesh Rajappa
	•	Aayush Ramkumar

⸻

📄 License

MIT License
