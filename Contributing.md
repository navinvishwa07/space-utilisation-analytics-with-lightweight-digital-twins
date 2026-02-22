your-repo-root/
│
├── backend/
│   │
│   ├── main.py
│   │
│   ├── controllers/
│   │   └── allocation_controller.py
│   │
│   ├── services/
│   │   ├── prediction_service.py
│   │   ├── matching_service.py
│   │   └── simulation_service.py
│   │
│   ├── domain/
│   │   ├── models.py
│   │   └── constraints.py
│   │
│   ├── repository/
│   │   └── data_repository.py
│   │
│   ├── utils/
│   │   ├── logger.py
│   │   └── config.py
│   │
│   └── data/
│       └── synthetic_dataset.csv
│
├── dashboard/
│   └── app.py
│
├── docs/
│   ├── MVP.md
│   ├── PRD.md
│   ├── Architecture.md
│   ├── AI_rules.md
│   ├── Skills.md
│   └── Plan.md
│
├── tests/
│   ├── test_prediction.py
│   ├── test_matching.py
│   └── test_constraints.py
│
├── requirements.txt
├── README.md
├── .gitignore
└── CONTRIBUTING.md