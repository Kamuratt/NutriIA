from pydantic import BaseModel
from typing import List, Optional

# Schema para exibir um ingrediente (não precisa de todos os campos do banco)
class IngredienteSchema(BaseModel):
    id: int
    descricao: str

    class Config:
        from_attributes = True

# Schema para exibir uma receita completa, incluindo seus ingredientes
class ReceitaSchema(BaseModel):
    id: int
    titulo: str
    url: str
    modo_preparo: str
    ingredientes: List[IngredienteSchema] = []

    class Config:
        from_attributes = True

# Schema para os dados que o usuário vai ENVIAR para a API
class UserRequestSchema(BaseModel):
    peso_kg: float
    altura_cm: float
    idade: int
    sexo: str  # 'homem' ou 'mulher'
    nivel_atividade: str # 'sedentario', 'leve', 'moderado', 'ativo'
    objetivo: str # 'perder_peso', 'manter_peso', 'ganhar_massa'

# Schema para a resposta que a API vai DEVOLVER
class DietPlanResponseSchema(BaseModel):
    plano_texto: str
    meta_calorica_calculada: float