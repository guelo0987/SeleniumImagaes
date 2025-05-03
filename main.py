"""
Descarga la primera imagen relevante encontrada en Google Imágenes
usando Selenium y requests, ignorando las categorías del encabezado.

Requisitos:
    pip install selenium webdriver-manager requests pillow
"""

import os
import time
import re
import urllib.parse
from typing import Optional, Tuple, List
from io import BytesIO

import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
try:
    from PIL import Image
except ImportError:
    print("Módulo Pillow no instalado. Instale con: pip install pillow")
    Image = None

def _iniciar_driver(headless: bool = False) -> webdriver.Chrome:
    """Configura e inicia Chrome con WebDriver Manager."""
    options = webdriver.ChromeOptions()
    if headless:  # Ejecutar sin interfaz gráfica
        options.add_argument("--headless=new")

    # Añadir opciones para mejorar estabilidad
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    # Evitar detección de automatización
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options,
    )


def _aceptar_cookies(driver: webdriver.Chrome, timeout: int = 5) -> None:
    """Pulsa el botón de cookies si aparece; ignora si no existe."""
    try:
        # Intentar diferentes patrones para el botón de cookies
        patrones = [
            "//button[contains(., 'Aceptar todo')]",
            "//button[contains(., 'Acepto')]",
            "//button[contains(., 'Accept all')]",
            "//button[contains(., 'I agree')]",
        ]

        for patron in patrones:
            try:
                boton = WebDriverWait(driver, timeout/len(patrones)).until(
                    EC.element_to_be_clickable((By.XPATH, patron))
                )
                boton.click()
                print(f"✅ Cookies aceptadas conD patrón: {patron}")
                return
            except:
                continue

        print("👉 No apareció el popup de cookies (o ya estaba aceptado).")
    except Exception as e:
        print(f"👉 No apareció el popup de cookies: {e}")


def _descargar_imagen(url: str, ruta_destino: str, timeout: int = 10) -> bool:
    """Intenta descargar la imagen específica y guardarla en disco."""
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200:
            # Asegurar que el directorio existe
            os.makedirs(os.path.dirname(ruta_destino), exist_ok=True)
            
            with open(ruta_destino, "wb") as f:
                f.write(resp.content)
            print(f"✅ Descargada: {ruta_destino}")
            return True
    except Exception as e:
        print(f"⚠️ Error al descargar {url}: {e}")
    return False


def _sanitizar_nombre_archivo(nombre: str) -> str:
    """Sanitiza un nombre de archivo para evitar caracteres problemáticos."""
    # Reemplazar caracteres no permitidos en nombres de archivo
    caracteres_prohibidos = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
    for char in caracteres_prohibidos:
        nombre = nombre.replace(char, '-')
    return nombre


def _es_imagen_no_miniatura(url: str) -> bool:
    """Verifica si una URL apunta a una imagen real y no a una miniatura."""
    # Evitar miniaturas de Google
    if "encrypted-tbn0.gstatic.com" in url:
        return False
    # Patrones para identificar imágenes reales
    if url.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
        return True
    if "googleusercontent.com" in url:
        return True
    # URLs de proveedores de imágenes conocidos
    proveedores = ["istock", "shutterstock", "flickr", "unsplash", "pexels", "pixabay"]
    if any(p in url.lower() for p in proveedores):
        return True
    return False


def _buscar_url_directa(driver: webdriver.Chrome) -> Optional[str]:
    """
    Enfoque alternativo que busca la URL en la página de resultados de Google Images.
    Este método es muy directo y funciona bien cuando Google no bloquea.
    """
    # Método 1: Buscar directamente en el DOM las imágenes grandes
    try:
        # Primero, buscamos todas las imágenes en la página
        todas_imagenes = driver.find_elements(By.TAG_NAME, "img")
        print(f"Encontradas {len(todas_imagenes)} imágenes en total")
        
        # Filtrar imágenes por tamaño mínimo (para evitar iconos)
        imagenes_filtradas = []
        for img in todas_imagenes:
            try:
                ancho = img.get_attribute("width")
                alto = img.get_attribute("height")
                
                # Solo considerar imágenes con tamaño razonable
                if ancho and alto and int(ancho) > 100 and int(alto) > 100:
                    imagenes_filtradas.append(img)
            except:
                continue
        
        print(f"Filtradas {len(imagenes_filtradas)} imágenes por tamaño")
        
        # Intentar extraer URL de las imágenes filtradas
        for img in imagenes_filtradas:
            for attr in ["src", "data-src", "data-url"]:
                url = img.get_attribute(attr)
                if url and url.startswith("http") and _es_imagen_no_miniatura(url):
                    print(f"Encontrada URL directa: {url[:60]}...")
                    return url
                    
        # Si no encontramos imágenes filtradas por tamaño, probamos con todas
        for img in todas_imagenes:
            for attr in ["src", "data-src", "data-url"]:
                url = img.get_attribute(attr)
                if url and url.startswith("http") and _es_imagen_no_miniatura(url):
                    print(f"Encontrada URL directa (sin filtrar): {url[:60]}...")
                    return url
    except Exception as e:
        print(f"Error al buscar URL directa: {e}")
    
    return None


def _buscar_imagenes_por_clases(driver: webdriver.Chrome) -> Optional[str]:
    """
    Busca imágenes en la página usando clases específicas que suelen
    contener las imágenes de resultados.
    """
    try:
        # Clases que suelen contener las imágenes de resultados en Google Images
        clases_contenedores = [
            ".islrc > div",  # Contenedores de la cuadrícula principal
            ".isv-r",        # Resultados de imagen
            "div[jscontroller='U4RaFc']",  # Controlador de imágenes
        ]
        
        for selector in clases_contenedores:
            try:
                print(f"Buscando con selector: {selector}")
                contenedores = driver.find_elements(By.CSS_SELECTOR, selector)
                print(f"Encontrados {len(contenedores)} contenedores")
                
                if contenedores:
                    # Saltamos el primer bloque si hay más de uno (podría ser categorías)
                    indice_inicio = 1 if len(contenedores) > 4 else 0
                    
                    # Revisamos cada contenedor en busca de imágenes
                    for i in range(indice_inicio, min(10, len(contenedores))):
                        contenedor = contenedores[i]
                        try:
                            # Buscar imágenes dentro del contenedor
                            imagenes = contenedor.find_elements(By.TAG_NAME, "img")
                            
                            for img in imagenes:
                                for attr in ["src", "data-src"]:
                                    url = img.get_attribute(attr)
                                    if url and url.startswith("http") and _es_imagen_no_miniatura(url):
                                        print(f"Encontrada imagen en contenedor {i}: {url[:60]}...")
                                        return url
                        except:
                            continue
            except Exception as e:
                print(f"Error con selector {selector}: {e}")
    
    except Exception as e:
        print(f"Error al buscar por clases: {e}")
    
    return None


def _hacer_click_y_obtener_imagen(driver: webdriver.Chrome) -> Optional[str]:
    """Hace clic en la primera imagen sustancial y obtiene la versión grande."""
    try:
        # Encontrar todas las imágenes visibles y hacer clic en la primera válida
        todas_imagenes = driver.find_elements(By.TAG_NAME, "img")
        
        # Filtrar por tamaño para evitar iconos y miniaturas
        for img in todas_imagenes:
            try:
                ancho = img.get_attribute("width")
                alto = img.get_attribute("height")
                
                if ancho and alto and int(ancho) > 100 and int(alto) > 100:
                    # Intentar hacer clic en esta imagen
                    print("Intentando hacer clic en imagen...")
                    driver.execute_script("arguments[0].scrollIntoView(true);", img)
                    time.sleep(1)
                    img.click()
                    print("Clic exitoso, buscando imagen grande...")
                    time.sleep(2)
                    
                    # Buscar la imagen grande después del clic
                    selectores_img_grande = [
                        "img.n3VNCb", "img.r48jcc", 
                        "img[jsname='HiaYvf']", "img[jsname='kn3ccd']",
                        "div.v4dQwb img", "a[jsname='sTFXNd'] img"
                    ]
                    
                    for selector in selectores_img_grande:
                        try:
                            img_grande = WebDriverWait(driver, 3).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                            )
                            url = img_grande.get_attribute("src")
                            if url and url.startswith("http") and _es_imagen_no_miniatura(url):
                                print(f"URL de imagen grande encontrada: {url[:60]}...")
                                return url
                        except:
                            continue
                            
                    # Intentar encontrar botón "Ver imagen"
                    botones_ver = driver.find_elements(By.XPATH, "//*[contains(text(), 'Ver imagen') or contains(text(), 'View image')]")
                    if botones_ver:
                        botones_ver[0].click()
                        print("Haciendo clic en 'Ver imagen'...")
                        time.sleep(2)
                        return driver.current_url
            except:
                continue
    
    except Exception as e:
        print(f"Error al hacer clic y obtener imagen: {e}")
    
    return None


def _buscar_imagenes_alt(driver: webdriver.Chrome, query: str) -> Optional[str]:
    """
    Intenta buscar directamente usando una URL alternativa
    que muestra directamente las imágenes.
    """
    try:
        # Construir URL directa de búsqueda de imágenes
        encoded_query = urllib.parse.quote(query)
        url_directa = f"https://www.google.com/search?q={encoded_query}&tbm=isch&hl=es"
        
        # Navegar a esta URL
        print(f"Navegando a URL directa: {url_directa}")
        driver.get(url_directa)
        time.sleep(3)
        
        # Intentar diferentes enfoques para obtener la imagen
        enfoques = [
            _buscar_url_directa,
            _buscar_imagenes_por_clases,
            _hacer_click_y_obtener_imagen
        ]
        
        for enfoque in enfoques:
            url = enfoque(driver)
            if url:
                return url
                
    except Exception as e:
        print(f"Error en búsqueda alternativa: {e}")
    
    return None


def descargar_primera_imagen(
        query: str,
        carpeta: str = "imagenes",
        headless: bool = False
) -> Tuple[bool, Optional[str]]:
    """
    Busca `query` en Google Imágenes y guarda la primera imagen válida encontrada
    de los resultados principales, ignorando el carrusel de categorías.

    Args:
        query: Texto a buscar.
        carpeta: Carpeta donde se guardará la imagen.
        headless: Ejecutar Chrome en modo headless.

    Returns:
        Tupla con (éxito, ruta de la imagen) o (False, None) si falló.
    """
    os.makedirs(carpeta, exist_ok=True)
    imagen_ruta = None
    driver = None

    try:
        driver = _iniciar_driver(headless)
        
        # Añadir un user agent real para evitar bloqueos
        driver.execute_cdp_cmd('Network.setUserAgentOverride', {
            "userAgent": 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        })
        
        # ENFOQUE 1: Método estándar con Google Images
        print("Intentando método estándar de búsqueda...")
        driver.get("https://images.google.com/")
        time.sleep(2)

        _aceptar_cookies(driver)

        # Escribir la búsqueda
        try:
            caja = driver.find_element(By.NAME, "q")
            caja.send_keys(query)
            caja.send_keys(Keys.RETURN)
            
            # Esperar a que carguen resultados
            print("Esperando que carguen los resultados...")
            time.sleep(5)
            
            # Intentar enfoques principales para obtener la URL
            url = None
            
            for enfoque in [_buscar_url_directa, _buscar_imagenes_por_clases, _hacer_click_y_obtener_imagen]:
                url = enfoque(driver)
                if url:
                    break
        except Exception as e:
            print(f"Error en método estándar: {e}")
            url = None
            
        # ENFOQUE 2: Si el método estándar falla, probar método alternativo
        if not url:
            print("Método estándar falló. Intentando método alternativo...")
            url = _buscar_imagenes_alt(driver, query)
        
        # Procesar la URL y descargar si la encontramos
        if url:
            # Sanitizar el nombre del archivo
            nombre_archivo = _sanitizar_nombre_archivo(query.replace(' ', '_'))
            destino = os.path.join(carpeta, f"{nombre_archivo}_1.jpg")
            
            # Descargar la imagen
            if _descargar_imagen(url, destino):
                imagen_ruta = destino
                return True, imagen_ruta

        print("❌ No se pudo encontrar/descargar la imagen.")
        return False, None

    except Exception as e:
        print(f"❌ Error general: {e}")
        return False, None

    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass


if __name__ == "__main__":
    exito, ruta = descargar_primera_imagen("gatos")
    if exito:
        print(f"✅ Imagen descargada exitosamente en: {ruta}")
    else:
        print("❌ No se pudo descargar la imagen.")