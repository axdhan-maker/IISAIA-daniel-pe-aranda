Prompts TP1

Contexto: quería ensayar a hacerlo con ChatGPT, pago el plan más económico y nunca había hecho algo así, me pareció buen ejercicio para medir la capacidad de ese modelo.

Prompt inicial: puedes crear una página web mockup? necesito un captcha con mala UI/UX para un proyecto de la universidad, solo eso, simplemente arranca la página web, resuelves el CAPTCHA y listo, dime si puedes o no y te paso la idea

la respuesta: 
Sí, puedo crear el mockup web interactivo.

Pásame la idea del CAPTCHA y puedo plantear una página donde:

Se cargue la interfaz.
Aparezca el CAPTCHA deliberadamente con mala UI/UX.
El usuario lo resuelva.
Se valide la respuesta.
Al resolverlo correctamente, se complete/avance la página.

Si quieres, también puedo hacer que el CAPTCHA tenga características específicas de mala UX: instrucciones ambiguas, elementos pequeños, contraste incómodo, orden confuso, feedback poco claro, etc., manteniéndolo como una simulación académica.

Siguiente prompt:
necesito un solo archivo index.html, quiero que sea un mock up del juego duck hunt, pero que el puntero para dispararle al pato se mueva con 2 valvulas industriales, de esas que hay que darles muchas vueltas para llegar al tope de una dirección, el pato debe moverse de manera completamente aleatoria subiendo y bajando, durante 1 minuto antes de escapar, cuando escape debe decir captcha fallida y aparecer un boton para intentarlo de nuevo, el puntero con que se le da click al pato es diferente al puntero del mouse y solo se controla con las valvulas, el boton para disparar para darle al pato hay que darle click 3 veces en rapida sucesión antes que dispare, al usuario no se le debe dar información de cuantos clicks lleva antes de disparar, graficamente debe parecerse al juego original, pero el pato debe verse como si hubieses puesto el boton tipico de "no soy un robot" sobre el sprite del pato, mal puesto de manera intencional, y el click solo debe funcionar si se le da al cuadrito blanco del "no soy un robot"

Explicación del prompt: me demoré determinando que quería hacer, no quería que se viera derivativo de los ejemplos que vimos en clase, recientemente jugué "Iron Nest" que se trata de apuntar una artillería, considerando distancia, azimut, cargas de polvora, etc. quería algo similar pero me parecia muy complicado para hacerlo correctamente, luego se me ocurrió que la mala UI se "burlara" (aunque no lo implementé) del usuario, en ese momento me hizo click en la mente y me acordé del perrito que se rie en el juego "Duck Hunt" para NES cuando se te escapa un pato, teniendo esta idea comencé a darle forma mientras escribia el prompt, la idea de darle click 3 veces seguidas vino de los "rage click" que me enseñó una vez una especialista en UI/UX, es una métrica que mide cuando alguien le da muchos click a algo porque no funciona, también es una protección para un simple click de suerte, esperaría que alguien que intenta resolver la CAPTCHA y no sabe lo de los 3 click haga "rage" y así si le funcione, la falta de feedback a la hora de dar click en el boton de disparar es a drede.

Respuesta del modelo:
Sí. Puedo hacer ese mockup en un único index.html, incluyendo la interacción de las dos válvulas, el puntero independiente, el movimiento aleatorio del pato, la ventana de 1 minuto, el disparo con triple-click oculto y el CAPTCHA superpuesto de forma deliberadamente defectuosa.

Hay una salvedad: no puedo reproducir exactamente los sprites/assets originales de Duck Hunt, pero sí puedo hacer una estética retro de NES muy cercana y dibujar el pato/CAPTCHA en el propio HTML/CSS/Canvas.

Pásame cualquier detalle adicional que quieras sobre cómo deben funcionar las dos válvulas (por ejemplo, una mueve horizontalmente y otra verticalmente), y te preparo el index.html completo

Mi respuesta:
si, así tal cual

El modelo generó una imagen, aunque no se la solicité:

<img src="images/imagen generada por el modelo.png" alt="MockUp" width="800">

luego finalizó:

Listo. Generé el mockup completo en un único archivo:

Descargar index.html

Incluye las dos válvulas, puntero independiente, pato con CAPTCHA superpuesto, movimiento aleatorio durante 60 segundos, triple clic oculto para disparar y condición de impacto únicamente sobre el cuadro de “No soy un robot”.

Luego no hice más prompts, la imagen mockup quedo muy bien, pero el "arte" generado para el CAPTCHA real quedo tosco, a mi punto de vista quedo perfecto, con un estilo de programas indie de los 90 y yo simplemente quedé encantado con el resultado, aquí esta la prueba que se puede completar el CAPTCHA.

<img src="images/prueba de exito.png" alt="CAPTCHA completed" width="800">


###
También comparto la conversación:
https://chatgpt.com/share/6aa0d422-f99c-83e9-8c79-137da0cf3465