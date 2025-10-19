# api/schemas.py
from pydantic import BaseModel
from typing import List, Optional, Any

# Schema simplificado para exibir a descrição de um ingrediente
# A estrutura vem do JSON, não de uma tabela separada
class IngredienteSchema(BaseModel):
    descricao: str

# Schema para exibir uma receita completa
class ReceitaSchema(BaseModel):
    id: int
    titulo: str
    modo_preparo: Optional[str] = ""
    ingredientes: List[IngredienteSchema] = []

    class Config:
        from_attributes = True

# Schema para os dados que o usuário envia para a API
class UserRequestSchema(BaseModel):
    peso_kg: float
    altura_cm: float
    idade: int
    sexo: str
    nivel_atividade: str
    objetivo: str
    restricoes: List[str] = []
    tipo_plano: str
    # --- [INÍCIO DA ATUALIZAÇÃO] ---
    # Novos campos de saúde, ambos opcionais
    doencas_cronicas: Optional[List[str]] = []
    circunferencia_cintura: Optional[float] = None
    # --- [FIM DA ATUALIZAÇÃO] ---

# Schema para a resposta que a API devolve
class DietPlanResponseSchema(BaseModel):
    plano_texto: str
    meta_calorica_calculada: float
    receitas_detalhadas: List[ReceitaSchema] = []
