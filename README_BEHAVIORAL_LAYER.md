# Couche comportementale et garde-fou pédagogique — TutoratAI

## Fichiers
- `services/behavioral_state_service.py`
- `services/cognitive_control_service.py`
- `services/pedagogical_policy_service.py`
- `services/pedagogical_response_guard.py`
- `tests/test_behavioral_layer.py`

## Installation
Copier les quatre fichiers de `services/` dans `C:\Users\ambro\projects\tutorat_ai\services\` et le test dans `C:\Users\ambro\projects\tutorat_ai\tests\`.

## Test
```cmd
python -m pytest tests\test_behavioral_layer.py -q
```

## Ordre d'intégration dans `/enseignant-virtuel`
1. identifier l'intention
2. obtenir le verdict de validation
3. diagnostiquer l'état comportemental
4. détecter le contrôle cognitif
5. choisir la politique pédagogique
6. générer la réponse de Naïma
7. passer la réponse dans le garde-fou
8. régénérer si nécessaire
9. enregistrer les nouveaux champs dans `TraceApprentissage`

Ne pas modifier `ValidationEngine` pour cette étape.
