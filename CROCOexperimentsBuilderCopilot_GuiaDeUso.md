# **CROCO Experiments Builder Copilot — Guía de uso**

Esta guía explica **cómo usar el GPT “CROCO Experiments Builder Copilot”** como parte del flujo de trabajo con **CROCOEXP\_BUILDER**.

El Copilot no reemplaza el criterio científico del investigador. Funciona como **copiloto cognitivo**: ayuda a diseñar, traducir, validar y diagnosticar experimentos CROCO de forma explícita y trazable.

---

## **1\. Qué es (y qué no es) el Copilot**

### **Qué es**

El Copilot es un asistente especializado que:

* ayuda a **diseñar experimentos CROCO** dentro del framework CROCOEXP\_BUILDER  
* traduce **tutoriales, papers y ejemplos CROCO** a configuraciones explícitas de experimento  
* anticipa y clasifica errores frecuentes  
* ayuda a interpretar logs de compilación y ejecución

### **Qué NO es**

* ❌ No ejecuta código  
* ❌ No modifica tu sistema ni tus archivos  
* ❌ No toma decisiones por vos

El Copilot **propone y explica**. El investigador decide y firma el paper.

---

## **2\. Modelo mental recomendado**

Para usar bien el Copilot conviene adoptar este marco:

* CROCO es una **librería científica**, no una aplicación cerrada  
* Un experimento CROCO es el resultado de decisiones explícitas:  
  * directivas de compilación (CPP)  
  * parámetros numéricos  
  * inputs  
  * forma de ejecución

El Copilot está diseñado para ayudarte a **hacer visibles esas decisiones**.

---

## **3\. Cuándo usar el Copilot**

El Copilot es especialmente útil en:

* diseño inicial de un experimento  
* traducción de tutoriales CROCO  
* revisión de coherencia antes de compilar  
* diagnóstico de errores de compilación o runtime  
* onboarding de nuevos integrantes del equipo

No es necesario usarlo en cada corrida, pero **sí en cada decisión importante**.

---

## **4\. Modos de uso**

El Copilot soporta dos modos conceptuales:

### **Learning mode (por defecto)**

Pensado para:

* usuarios nuevos  
* exploración de configuraciones  
* discusión conceptual

Características:

* puede proponer archivos completos  
* explicaciones explícitas (pero concisas)  
* foco en el significado físico y numérico

### **Production mode**

Pensado para:

* usuarios experimentados  
* trabajo repetitivo o sistemático

Características:

* propone diffs o snippets  
* explicaciones mínimas  
* foco en coherencia y trazabilidad

Podés indicar el modo explícitamente en cualquier momento.

---

## **5\. Cómo pedir ayuda correctamente**

### **Diagnóstico de errores**

Cuando algo falla, es recomendable proporcionar:

* el log relevante (`compile.log` o `run.log`)  
* los archivos de configuración involucrados (`run.env`, `cppdefs.h`, `param.h`)

Ejemplo:

“Este experimento falla en runtime. Acá están mi run.log y run.env. ¿Podés clasificar el error?”

El Copilot **siempre empezará clasificando el problema** antes de proponer cambios.

---

### **Validación previa**

Antes de compilar, podés pedir una revisión de coherencia:

“Quiero validar esta configuración antes de compilar. Acá están cppdefs.h, param.h y run.env.”

Esto ayuda a detectar inconsistencias tempranas.

---

## **6\. Traducción de tutoriales y papers**

Una de las funciones centrales del Copilot es actuar como **translator**.

Cuando trabajás con:

* tutoriales oficiales de CROCO  
* papers  
* ejemplos clásicos

podés pedir explícitamente una traducción:

“Estoy siguiendo el tutorial BASIN. ¿Cómo lo traduzco a un experimento CROCOEXP\_BUILDER?”

El Copilot:

1. identifica las suposiciones implícitas del tutorial  
2. las hace explícitas  
3. las mapea a archivos concretos del experimento

El resultado **no es único**: es una traducción razonable y documentada.

---

## **7\. Taxonomía de errores**

El Copilot clasifica los problemas usando una taxonomía explícita:

* A: Infraestructura (Docker / host)  
* B: Entorno del builder  
* C: Compilación / toolchain  
* D: Configuración del experimento (modelo efectivo)  
* E: Inputs y paths  
* F: Runtime / I/O  
* G: Runtime numérico / físico

Esto evita confundir:

* errores científicos con bugs  
* problemas de infraestructura con problemas de modelo

---

## **8\. Buenas prácticas**

* Usar el Copilot **antes** de compilar ahorra tiempo  
* Ejecutar siempre un `--dry-run` luego de cambios importantes  
* Documentar las decisiones relevantes sugeridas por el Copilot  
* Tratar las inestabilidades numéricas como parte del trabajo científico, no como fallas

---

## **9\. Limitaciones**

El Copilot:

* no reemplaza el conocimiento de CROCO  
* no garantiza que un experimento sea “correcto”  
* no valida resultados científicos

Su función es **reducir fricción cognitiva**, no eliminar la complejidad.

---

## **10\. En resumen**

Usado correctamente, el CROCO Experiments Builder Copilot:

* acelera la curva de aprendizaje  
* hace explícitas decisiones implícitas  
* mejora trazabilidad y comunicación dentro del equipo

Pensalo como el **técnico de laboratorio digital** del grupo.

