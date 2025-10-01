import pandas as pd

# O número do header pode precisar de ajuste (ex: header=1 ou header=2)
# dependendo do arquivo que você baixou.
caminho_do_arquivo = "../data/raw/Taco-4a-Edicao.xlsx"
df = pd.read_excel(caminho_do_arquivo, header=0)

colunas_de_interesse = [
    'Descrição dos alimentos',
    'Energia',
    'Proteína',
    'Lipídeos',
    'Carboidrato', # Atenção aqui ao nome exato do arquivo
    'Fibra Alimentar'
]

df = df[colunas_de_interesse]

df = df.drop(index = 0)

df = df.rename(columns={
    'Descrição dos alimentos': 'alimento',
    'Energia': 'calorias',
    'Proteína': 'proteina',
    'Lipídeos': 'lipideos',
    'Carboidrato': 'carboidratos',
    'Fibra Alimentar': 'fibras'
})

# Passo 2: Converter tudo para número (isso vai transformar 'NA' e 'Tr' em "buracos" ou NaN)
for coluna in ['calorias', 'proteina', 'lipideos', 'carboidratos', 'fibras']:
    df[coluna] = pd.to_numeric(df[coluna], errors='coerce')

# Passo 3: Remover as linhas de categoria que sobraram
# As linhas de categoria (ex: "Frutas") não têm valor de calorias, então viraram NaN no passo anterior.
# O comando abaixo remove qualquer linha que tenha NaN na coluna 'calorias'.
df.dropna(subset=['calorias'], inplace=True)

# Passo 4: Trocar qualquer outro valor vazio que sobrou por 0
df = df.fillna(0)

df.to_csv('tabela_taco_processada.csv', index=False)
