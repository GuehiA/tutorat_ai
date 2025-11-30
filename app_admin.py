from flask import Flask, render_template, request, redirect
from sqlalchemy import create_engine, MetaData, Table
from sqlalchemy.orm import sessionmaker

app = Flask(__name__)
engine = create_engine('sqlite:///plateforme_bilingue.db')
metadata = MetaData(bind=engine)
metadata.reflect()

Session = sessionmaker(bind=engine)
db_session = Session()

# Ref tables
Niveaux = metadata.tables['niveaux']
Matieres = metadata.tables['matieres']
Unites = metadata.tables['unites']
Lecons = metadata.tables['lecons']
Exercices = metadata.tables['exercices']

@app.route("/")
def index():
    return render_template("base.html")

@app.route("/ajouter-niveau", methods=["GET", "POST"])
def ajouter_niveau():
    if request.method == "POST":
        nom = request.form["nom"]
        db_session.execute(Niveaux.insert().values(nom=nom))
        db_session.commit()
        return redirect("/")
    return render_template("ajouter_niveau.html")

@app.route("/ajouter-matiere", methods=["GET", "POST"])
def ajouter_matiere():
    niveaux = db_session.query(Niveaux).all()
    if request.method == "POST":
        nom = request.form["nom"]
        niveau_id = request.form["niveau_id"]
        db_session.execute(Matieres.insert().values(nom=nom, niveau_id=niveau_id))
        db_session.commit()
        return redirect("/")
    return render_template("ajouter_matiere.html", niveaux=niveaux)

# Tu pourras continuer de la même manière pour unités, leçons et exercices.

if __name__ == "__main__":
    app.run(debug=True)
