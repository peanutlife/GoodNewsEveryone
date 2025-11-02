# test_routes.py
from src.main import create_app

app = create_app()

with app.app_context():
    print("All registered routes:")
    for rule in app.url_map.iter_rules():
        print(f"{rule.endpoint:40s} {rule.rule}")
