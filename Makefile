.PHONY: install run clean

install:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt

run:
	.venv/bin/streamlit run app.py

clean:
	rm -rf .venv __pycache__ .streamlit
