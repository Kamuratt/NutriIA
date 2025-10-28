def calcular_tmb(peso_kg: float, altura_cm: float, idade: int, sexo: str) -> float:
    """
    Calcula a Taxa Metabólica Basal (TMB) usando a equação de Mifflin-St Jeor.
    
    Args:
        peso_kg (float): Peso da pessoa em quilogramas.
        altura_cm (float): Altura da pessoa em centímetros.
        idade (int): Idade da pessoa em anos.
        sexo (str): Sexo biológico ('homem' ou 'mulher').

    Returns:
        float: A TMB em kcal/dia.
    """
    sexo = sexo.lower()
    if sexo == 'masculino':
        tmb = (10 * peso_kg) + (6.25 * altura_cm) - (5 * idade) + 5
        return tmb
    elif sexo == 'feminino':
        tmb = (10 * peso_kg) + (6.25 * altura_cm) - (5 * idade) - 161
        return tmb
    else:
        # Lança um erro se o sexo não for um dos valores esperados
        raise ValueError("Sexo deve ser 'masculino' ou 'feminino'.")

def calcular_meta_calorica(tmb: float, nivel_atividade: str, objetivo: str) -> float:
    """
    Calcula a meta calórica diária com base na TMB, nível de atividade e objetivo.

    Args:
        tmb (float): A Taxa Metabólica Basal calculada.
        nivel_atividade (str): Nível de atividade ('sedentario', 'leve', 'moderado', 'ativo').
        objetivo (str): O objetivo da dieta ('perder_peso', 'manter_peso', 'ganhar_massa').

    Returns:
        float: A meta de calorias diárias recomendada.
    """
    fatores_atividade = {
        'sedentario': 1.2,
        'leve': 1.375,
        'moderado': 1.55,
        'ativo': 1.725
    }

    multiplicador_objetivo = {
        'perder_peso': 0.80,  # Déficit de 20%
        'manter_peso': 1.0,   # Manutenção
        'ganhar_massa': 1.20 # Superávit de 20%
    }
    
    # Valida as entradas
    fator_atividade = fatores_atividade.get(nivel_atividade.lower())
    if fator_atividade is None:
        raise ValueError("Nível de atividade inválido. Use 'sedentario', 'leve', 'moderado' ou 'ativo'.")

    multiplicador = multiplicador_objetivo.get(objetivo.lower())
    if multiplicador is None:
        raise ValueError("Objetivo inválido. Use 'perder_peso', 'manter_peso' ou 'ganhar_massa'.")

    # Calcula o gasto calórico diário total (TDEE)
    gasto_calorico_diario = tmb * fator_atividade
    
    # Aplica o ajuste para o objetivo final
    meta_calorica = gasto_calorico_diario * multiplicador
    
    return meta_calorica