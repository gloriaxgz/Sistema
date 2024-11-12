import streamlit as st
import geopandas as gpd
import pandas as pd
import folium
from shapely.geometry import Point
from streamlit_folium import folium_static
from branca.colormap import LinearColormap
from geopy.distance import geodesic


@st.cache_data
def carregar_dados():
    gdf = gpd.read_file("Mapas/JSON/Media_RPC.geojson")
    supermercados_df = pd.read_csv("GoogleAPI/estabelecimentos_bauru.csv")
    bauru_gdf = gpd.read_file("Mapas/Shapefile_Bauru.shp")
    densidade_gdf = gpd.read_file("Mapas/Densidade/densidade.shp")
    gdf['Categoria'] = gdf['Categoria'].fillna(0)
    

    gdf = gdf.to_crs(epsg=4326)
    bauru_gdf = bauru_gdf.to_crs(epsg=4326)
    densidade_gdf = densidade_gdf.to_crs(epsg=4326)
    vias_gdf = gpd.read_file("Mapas/Vias/vias_osm.shp")
    vias_gdf = vias_gdf[vias_gdf['highway'].isin(['secondary', 'tertiary'])].to_crs(epsg=4326)

    return gdf, supermercados_df, bauru_gdf, densidade_gdf, vias_gdf


def calcular_distancia_via(ponto_usuario, vias_gdf):
    min_distancia = float('inf')
    ponto_usuario_geom = gpd.GeoSeries([Point(ponto_usuario[1], ponto_usuario[0])], crs="EPSG:4326").to_crs(epsg=3857)
    vias_gdf = vias_gdf.to_crs(epsg=3857)
    
    for _, row in vias_gdf.iterrows():
        distancia = row['geometry'].distance(ponto_usuario_geom.iloc[0])
        min_distancia = min(min_distancia, distancia)
    
    return min_distancia


def criar_mapa_renda_com_concorrentes(gdf, supermercados_df, densidade_gdf, renda_minima, densidade_minima, mostrar_concorrentes, mostrar_correlatos):
    colormap = LinearColormap(colors=['#fff4e0', '#ff0000'], vmin=gdf['Categoria'].min(), vmax=5000)
    colormap.caption = "Renda Per Capita Média (até 5 mil)"
    m = folium.Map(location=[-22.3145, -49.058], zoom_start=12)
    

    folium.GeoJson(
        gdf,
        style_function=lambda feature: {
            "fillColor": colormap(feature['properties'].get('Categoria', 0))
            if feature['properties'].get('Categoria') >= renda_minima else "#FFFFFF00",
            "color": "black",
            "weight": 0.6,
            "fillOpacity": 0.6 if feature['properties'].get('Categoria') >= renda_minima else 0,
        },
        tooltip=folium.GeoJsonTooltip(fields=["Categoria"], aliases=["Renda Per Capita Média:"], localize=True)
    ).add_to(m)
    

    folium.GeoJson(
        densidade_gdf,
        style_function=lambda feature: {
            "color": "black",
            "weight": 0.6 if (feature['properties'].get('densidade', 0) or 0) < densidade_minima else 2.5,
            "fillOpacity": 0
        },
        tooltip=folium.GeoJsonTooltip(fields=["densidade"], aliases=["Densidade Populacional:"], localize=True)
    ).add_to(m)
    
    cores_estabelecimentos = {
        "pharmacy": "purple", "shopping_mall": "orange", "supermarket": "red", 
        "convenience_store": "green", "bakery": "blue", "restaurant": "darkblue", "liquor_store": "darkred"
    }
    
    for idx, row in supermercados_df.iterrows():
        tipo_estabelecimento = row['type']
        cor = cores_estabelecimentos.get(tipo_estabelecimento, "gray")
        
        if tipo_estabelecimento == "supermarket" and not mostrar_concorrentes:
            continue
        elif tipo_estabelecimento != "supermarket" and not mostrar_correlatos:
            continue
        
        folium.CircleMarker(
            location=(row['latitude'], row['longitude']),
            radius=4,
            color=cor,
            fill=True,
            fill_color=cor,
            fill_opacity=0.7,
            tooltip=f"{row['name']} ({tipo_estabelecimento})"
        ).add_to(m)
    
    colormap.add_to(m)
    return m


def criar_mapa_ponto(supermercados_df, bauru_gdf, ponto_usuario, distancia_minima):
    m = folium.Map(location=[-22.3145, -49.058], zoom_start=13)
    folium.GeoJson(bauru_gdf).add_to(m)
    
    if ponto_usuario:
        folium.Marker(location=ponto_usuario, tooltip="Ponto Selecionado", icon=folium.Icon(color="blue")).add_to(m)
        folium.Circle(location=ponto_usuario, radius=distancia_minima, color="blue", fill=True, fill_opacity=0.2).add_to(m)
    
    for idx, row in supermercados_df.iterrows():
        supermercado_ponto = (row['latitude'], row['longitude'])
        if ponto_usuario:
            distancia = geodesic(ponto_usuario, supermercado_ponto).meters
            if distancia <= distancia_minima:
                folium.Marker(location=supermercado_ponto, tooltip=row['name'], icon=folium.Icon(color="red")).add_to(m)
    
    m.add_child(folium.LatLngPopup())
    return m


def calcular_pontuacao(ponto_usuario, supermercados_df, densidade_gdf, vias_gdf, gdf, distancia_concorrentes, distancia_negocios, densidade_minima, renda_minima):
    
    num_concorrentes = sum(
        1 for _, row in supermercados_df[supermercados_df['type'] == 'supermarket'].iterrows()
        if geodesic(ponto_usuario, (row['latitude'], row['longitude'])).meters <= distancia_concorrentes * 1000
    )
    pontuacao_concorrentes = max(0, 10 - (num_concorrentes / 10) * 10)

    num_correlatos = sum(
        1 for _, row in supermercados_df[supermercados_df['type'].isin(['pharmacy', 'shopping_mall', 'convenience_store', 'bakery', 'restaurant', 'liquor_store'])].iterrows()
        if geodesic(ponto_usuario, (row['latitude'], row['longitude'])).meters <= distancia_negocios * 1000
    )
    pontuacao_correlatos = min(10, (num_correlatos / 10) * 10)

    densidade_area = next((row['densidade'] for _, row in densidade_gdf.iterrows() if row['geometry'].contains(Point(ponto_usuario[1], ponto_usuario[0]))), 0)
    pontuacao_densidade = min(10, (densidade_area / densidade_minima) * 10) if densidade_area > 0 else 0

    distancia_via = calcular_distancia_via(ponto_usuario, vias_gdf)
    pontuacao_acessibilidade = max(0, 10 - (distancia_via / 1000) * 10)

    renda_area = next((row['Categoria'] for _, row in gdf.iterrows() if row['geometry'].contains(Point(ponto_usuario[1], ponto_usuario[0]))), 0)
    pontuacao_renda = min(10, (renda_area / renda_minima) * 10) if renda_area >= renda_minima else 0

    nota_final = (pontuacao_concorrentes + pontuacao_correlatos + pontuacao_densidade + pontuacao_acessibilidade + pontuacao_renda) / 5
    
    return {
        "Concorrentes": pontuacao_concorrentes,
        "Negócios Correlatos": pontuacao_correlatos,
        "Densidade Populacional": pontuacao_densidade,
        "Acessibilidade": pontuacao_acessibilidade,
        "Renda Per Capita": pontuacao_renda,
        "Nota Final": nota_final
    }

st.title("Análise de Pontos de Instalação de Supermercados")

gdf, supermercados_df, bauru_gdf, densidade_gdf, vias_gdf = carregar_dados()

st.sidebar.title("Selecione o Ponto para Análise")
latitude = st.sidebar.number_input("Latitude do ponto", value=-22.3145, format="%.6f")
longitude = st.sidebar.number_input("Longitude do ponto", value=-49.0580, format="%.6f")
ponto_usuario = (latitude, longitude) if latitude and longitude else None

mostrar_concorrentes = st.sidebar.checkbox("Mostrar Concorrentes", value=True)
mostrar_correlatos = st.sidebar.checkbox("Mostrar Negócios Correlatos", value=True)

distancia_concorrentes = st.sidebar.slider("Distância Máxima dos Concorrentes (km)", 0.1, 5.0, 1.0)
distancia_negocios = st.sidebar.slider("Distância Máxima dos Negócios Correlatos (km)", 0.1, 5.0, 1.0)
densidade_minima = st.sidebar.slider("Densidade Populacional Mínima (hab/km²)", 0, 10000, 5000)
renda_minima = st.sidebar.slider("Renda Per Capita Média Mínima (R$)", 0, 5000, 1000)


if ponto_usuario:

    pontuacoes = calcular_pontuacao(
        ponto_usuario, supermercados_df, densidade_gdf, vias_gdf, gdf,
        distancia_concorrentes, distancia_negocios, densidade_minima, renda_minima
    )

    st.subheader("Mapa com Análise de Renda e Concorrentes")
    mapa_renda_concorrentes = criar_mapa_renda_com_concorrentes(
        gdf, supermercados_df, densidade_gdf, renda_minima, densidade_minima,
        mostrar_concorrentes=mostrar_concorrentes, mostrar_correlatos=mostrar_correlatos
    )
    folium_static(mapa_renda_concorrentes)

    st.subheader("Mapa de Seleção de Ponto")
    mapa_ponto = criar_mapa_ponto(supermercados_df, bauru_gdf, ponto_usuario, distancia_concorrentes * 1000)
    folium_static(mapa_ponto)

    st.subheader("Pontuações do Ponto Selecionado")
    for criterio, nota in pontuacoes.items():
        st.write(f"{criterio}: {nota:.2f}/10")

