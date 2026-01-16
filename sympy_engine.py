"""
Moteur de calcul symbolique pour vérifications mathématiques exactes
Ne modifie PAS les modèles existants - infère automatiquement le type d'exercice
"""
from sympy import (
    symbols, sympify, simplify, expand, factor, cancel,
    solve, Eq, diff, integrate, limit,
    solveset, S, Poly, fraction, together,
    sqrt, sin, cos, tan, log, exp, pi, E, I
)
from sympy.parsing.sympy_parser import (
    parse_expr, standard_transformations,
    implicit_multiplication, convert_xor
)
import re
from typing import Optional, Tuple, Union, List, Dict, Any

# Transformations pour le parsing
TRANSFORMATIONS = standard_transformations + (
    implicit_multiplication,
    convert_xor,
)

class MathVerifier:
    """
    Vérificateur mathématique qui détermine automatiquement le type d'exercice
    et vérifie la réponse de l'élève avec SymPy
    """
    
    def __init__(self):
        self.supported_types = [
            'equation', 'derivation', 'integration',
            'simplification', 'factorisation', 'expression',
            'limit', 'inequality', 'system'
        ]
    
    def infer_exercise_type(self, question: str, answer_expected: str) -> str:
        """
        Détermine automatiquement le type d'exercice mathématique
        """
        question_lower = question.lower()
        answer_lower = answer_expected.lower()
        
        # Motifs pour détecter le type
        patterns = {
            'equation': [r'solve', r'r[ée]soudre', r'equation', r'x\s*=', r'find x'],
            'derivation': [r'deriv', r'differentiate', r"f\'\(", r'd/dx'],
            'integration': [r'integral', r'∫', r'antiderivative'],
            'simplification': [r'simplify', r'reduce', r'expression'],
            'factorisation': [r'factor', r'factorize', r'factorise'],
            'limit': [r'limit', r'lim_', r'→'],
            'inequality': [r'inequality', r'<', r'>', r'≤', r'≥'],
            'system': [r'system', r'solve for', r'and']
        }
        
        for ex_type, pattern_list in patterns.items():
            for pattern in pattern_list:
                if re.search(pattern, question_lower, re.IGNORECASE):
                    return ex_type
        
        # Par défaut
        return 'expression'
    
    def clean_math_expression(self, expr: str) -> str:
        """
        Nettoie une expression mathématique pour SymPy
        """
        if not expr or expr.strip() == '':
            return ''
        
        expr = expr.strip()
        
        # Remplacements courants
        replacements = {
            '×': '*',
            '÷': '/',
            '^': '**',
            '²': '**2',
            '³': '**3',
            'π': 'pi',
            '√': 'sqrt',
            '∞': 'oo',
            '≈': '~',
            '≠': '!=',
            '≤': '<=',
            '≥': '>=',
            '∠': 'angle',
            '°': 'deg',
            '\\[': '$',
            '\\]': '$',
            '\\(': '$',
            '\\)': '$',
        }
        
        for old, new in replacements.items():
            expr = expr.replace(old, new)
        
        # Supprime les balises HTML
        expr = re.sub(r'<[^>]+>', '', expr)
        
        # Nettoie les espaces autour des opérateurs
        expr = re.sub(r'\s*([+\-*/^=<>])\s*', r'\1', expr)
        
        # Remplace les fractions Unicode
        expr = re.sub(r'(\d+)/(\d+)', r'(\1)/(\2)', expr)
        
        return expr.strip()
    
    def extract_variables(self, expr: str) -> List[str]:
        """
        Extrait les variables d'une expression
        """
        try:
            parsed = parse_expr(expr, transformations=TRANSFORMATIONS)
            return [str(v) for v in parsed.free_symbols]
        except:
            # Par défaut, on suppose 'x'
            return ['x']
    
    def verify_equation(self, student_answer: str, expected_answer: str, 
                       question_context: str = "") -> Dict[str, Any]:
        """
        Vérifie une équation ou une résolution
        """
        try:
            # Nettoie les expressions
            student_clean = self.clean_math_expression(student_answer)
            expected_clean = self.clean_math_expression(expected_answer)
            
            if not student_clean or not expected_clean:
                return {'verified': False, 'error': 'Empty expressions'}
            
            # Extrait les variables
            vars_student = self.extract_variables(student_clean)
            vars_expected = self.extract_variables(expected_clean)
            all_vars = list(set(vars_student + vars_expected))
            
            if not all_vars:
                # Comparaison d'expressions constantes
                expr_student = parse_expr(student_clean, transformations=TRANSFORMATIONS)
                expr_expected = parse_expr(expected_clean, transformations=TRANSFORMATIONS)
                
                simplified_student = simplify(expr_student)
                simplified_expected = simplify(expr_expected)
                
                is_equal = simplify(simplified_student - simplified_expected) == 0
                
                return {
                    'verified': True,
                    'is_correct': bool(is_equal),
                    'type': 'equation',
                    'student_value': str(simplified_student),
                    'expected_value': str(simplified_expected),
                    'equivalence': str(is_equal)
                }
            
            # Pour les équations avec variables
            # Essaye de résoudre l'équation de l'élève
            try:
                # Si la réponse de l'élève est déjà une solution
                if '=' in student_clean:
                    lhs, rhs = student_clean.split('=', 1)
                    expr = parse_expr(lhs, transformations=TRANSFORMATIONS) - \
                           parse_expr(rhs, transformations=TRANSFORMATIONS)
                else:
                    expr = parse_expr(student_clean, transformations=TRANSFORMATIONS)
                
                # Si la réponse attendue est une équation
                if '=' in expected_clean:
                    lhs_exp, rhs_exp = expected_clean.split('=', 1)
                    expr_expected_eq = parse_expr(lhs_exp, transformations=TRANSFORMATIONS) - \
                                       parse_expr(rhs_exp, transformations=TRANSFORMATIONS)
                    
                    # Résout l'équation attendue
                    solutions = solve(expr_expected_eq, symbols(all_vars[0]))
                    
                    # Vérifie si la réponse de l'élève est dans les solutions
                    student_value = simplify(expr)
                    is_solution = any(simplify(student_value - sol) == 0 for sol in solutions)
                    
                    return {
                        'verified': True,
                        'is_correct': bool(is_solution),
                        'type': 'equation',
                        'solutions': [str(sol) for sol in solutions],
                        'student_value': str(student_value),
                        'is_solution': is_solution
                    }
                else:
                    # Comparaison directe d'expressions
                    expr_expected = parse_expr(expected_clean, transformations=TRANSFORMATIONS)
                    is_equal = simplify(expr - expr_expected) == 0
                    
                    return {
                        'verified': True,
                        'is_correct': bool(is_equal),
                        'type': 'expression',
                        'student_expression': str(expr),
                        'expected_expression': str(expr_expected),
                        'equivalence': str(is_equal)
                    }
                    
            except Exception as e:
                # Fallback: comparaison numérique
                return self.verify_numerical_equivalence(student_clean, expected_clean)
                
        except Exception as e:
            return {
                'verified': False,
                'error': f'Equation verification error: {str(e)}',
                'type': 'equation'
            }
    
    def verify_derivation(self, student_answer: str, expected_answer: str,
                         function_expr: str = "") -> Dict[str, Any]:
        """
        Vérifie une dérivée
        """
        try:
            student_clean = self.clean_math_expression(student_answer)
            expected_clean = self.clean_math_expression(expected_answer)
            
            if not student_clean or not expected_clean:
                return {'verified': False, 'error': 'Empty expressions'}
            
            # Extrait la variable (par défaut 'x')
            vars_student = self.extract_variables(student_clean)
            var = vars_student[0] if vars_student else 'x'
            
            x = symbols(var)
            
            # Parse les expressions
            student_expr = parse_expr(student_clean, transformations=TRANSFORMATIONS)
            expected_expr = parse_expr(expected_clean, transformations=TRANSFORMATIONS)
            
            # Simplifie
            student_simplified = simplify(student_expr)
            expected_simplified = simplify(expected_expr)
            
            # Vérifie l'égalité
            is_equal = simplify(student_simplified - expected_simplified) == 0
            
            return {
                'verified': True,
                'is_correct': bool(is_equal),
                'type': 'derivation',
                'student_derivative': str(student_simplified),
                'expected_derivative': str(expected_simplified),
                'equivalence': str(is_equal)
            }
            
        except Exception as e:
            return {
                'verified': False,
                'error': f'Derivation verification error: {str(e)}',
                'type': 'derivation'
            }
    
    def verify_numerical_equivalence(self, student_expr: str, expected_expr: str,
                                   num_tests: int = 3) -> Dict[str, Any]:
        """
        Vérifie l'équivalence numérique en testant avec des valeurs aléatoires
        """
        try:
            student_clean = self.clean_math_expression(student_expr)
            expected_clean = self.clean_math_expression(expected_expr)
            
            expr_student = parse_expr(student_clean, transformations=TRANSFORMATIONS)
            expr_expected = parse_expr(expected_clean, transformations=TRANSFORMATIONS)
            
            # Extrait les variables
            variables = list(expr_student.free_symbols | expr_expected.free_symbols)
            
            if not variables:
                # Expressions constantes
                val_student = float(expr_student.evalf())
                val_expected = float(expr_expected.evalf())
                
                is_equal = abs(val_student - val_expected) < 1e-10
                
                return {
                    'verified': True,
                    'is_correct': bool(is_equal),
                    'type': 'numerical',
                    'student_value': val_student,
                    'expected_value': val_expected,
                    'difference': abs(val_student - val_expected),
                    'tolerance': 1e-10
                }
            
            # Test avec plusieurs valeurs aléatoires
            import random
            all_equal = True
            
            for _ in range(num_tests):
                # Génère des valeurs aléatoires
                substitutions = {}
                for var in variables:
                    # Évite 0 et les valeurs trop grandes
                    substitutions[var] = random.uniform(-5, 5)
                    while abs(substitutions[var]) < 0.1:
                        substitutions[var] = random.uniform(-5, 5)
                
                # Évalue les deux expressions
                val_student = float(expr_student.subs(substitutions).evalf())
                val_expected = float(expr_expected.subs(substitutions).evalf())
                
                if abs(val_student - val_expected) > 1e-8:
                    all_equal = False
                    break
            
            return {
                'verified': True,
                'is_correct': all_equal,
                'type': 'numerical_equivalence',
                'num_tests': num_tests,
                'all_tests_passed': all_equal
            }
            
        except Exception as e:
            return {
                'verified': False,
                'error': f'Numerical equivalence error: {str(e)}',
                'type': 'numerical'
            }
    
    def verify_answer(self, student_answer: str, expected_answer: str,
                     question: str = "") -> Dict[str, Any]:
        """
        Vérifie automatiquement une réponse mathématique
        """
        if not student_answer or not expected_answer:
            return {'verified': False, 'error': 'Missing answers'}
        
        # Nettoie les réponses
        student_clean = self.clean_math_expression(student_answer)
        expected_clean = self.clean_math_expression(expected_answer)
        
        if not student_clean or not expected_clean:
            return {'verified': False, 'error': 'Empty expressions after cleaning'}
        
        # Détermine le type d'exercice
        ex_type = self.infer_exercise_type(question, expected_clean)
        
        # Applique la vérification appropriée
        if ex_type == 'equation':
            return self.verify_equation(student_clean, expected_clean, question)
        elif ex_type == 'derivation':
            return self.verify_derivation(student_clean, expected_clean, question)
        elif ex_type == 'expression':
            return self.verify_numerical_equivalence(student_clean, expected_clean)
        else:
            # Pour tous les autres types, utilise l'équivalence numérique
            return self.verify_numerical_equivalence(student_clean, expected_clean)
    
    def get_symbolic_feedback(self, verification_result: Dict[str, Any]) -> str:
        """
        Génère un feedback basé sur la vérification symbolique
        """
        if not verification_result.get('verified', False):
            return "⚠️ La vérification mathématique automatique n'a pas pu être effectuée."
        
        if verification_result.get('is_correct', False):
            return "✅ **Vérification mathématique : CORRECTE**\n\n" \
                   f"Votre réponse a été vérifiée mathématiquement et est correcte.\n" \
                   f"Type d'exercice : {verification_result.get('type', 'inconnu')}"
        else:
            feedback = "❌ **Vérification mathématique : INCORRECTE**\n\n"
            feedback += f"Type d'exercice : {verification_result.get('type', 'inconnu')}\n\n"
            
            if 'student_value' in verification_result and 'expected_value' in verification_result:
                feedback += f"• Votre résultat : {verification_result['student_value']}\n"
                feedback += f"• Résultat attendu : {verification_result['expected_value']}\n"
            
            if 'solutions' in verification_result:
                feedback += f"• Solutions correctes : {', '.join(verification_result['solutions'])}\n"
            
            feedback += "\n**Conseil** : Vérifiez vos calculs étape par étape."
            return feedback

# Instance globale
math_verifier = MathVerifier()