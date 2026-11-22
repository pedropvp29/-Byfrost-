# Byfrost Social V9.3 — mídia unificada

Este projeto completo consolida os dois antigos módulos Python de mídia em **`blueprints/media.py`**. O `app.py` importa exclusivamente `blueprints.media`. Não são necessários arquivos `media_v9.py` nem `media_v10.py`.

## Projeto completo

A pasta `mysite/` do ZIP contém `main.py`, `flask_app.py`, `requirements.txt`, `.env.example`, todos os módulos `blueprints/`, templates de landing/login/app, o editor JavaScript em `static/`, e um exemplo WSGI em `deployment_examples/`.

O ZIP **não contém seu banco real, fotos, vídeos, senhas ou arquivo `.env`**. Ele inclui apenas o código e instruções. Dados de posts/fotos e vídeos que você já publicou devem ser mantidos no servidor.

## Instalação no PythonAnywhere (site existente)

1. **Faça backup primeiro** de `/home/Pedroteste/mysite/data/users.db`, de `/home/Pedroteste/mysite/data/byfrost_post_videos/`, do `.env` e dos arquivos de código atuais.
2. Se já usa a V9.2, prefira o ZIP **atualização**, que altera somente `blueprints/app.py` e acrescenta `blueprints/media.py`.
3. Se usar o ZIP **completo**, **não apague a pasta `mysite` existente** nem sobrescreva `data/users.db`, a pasta de vídeos ou `.env`. Faça a mesclagem apenas do código necessário.
4. Os arquivos antigos `blueprints/media_v9.py` e `blueprints/media_v10.py` deixam de ser necessários; depois de confirmar a atualização, podem ser removidos. Os novos módulos não os importam.
5. No Bash, se não usa virtualenv, execute:

   ```bash
   cd /home/Pedroteste/mysite
   python3.11 -m pip install --user -r requirements.txt
   python3.11 -m py_compile main.py flask_app.py blueprints/*.py
   python3.11 -c "from blueprints import media; print('media.py OK', media.MAX_POST_PHOTOS)"
   python3.11 -c "from flask_app import app; print('Byfrost OK')"
   ```

   **Se a aba Web indicar um virtualenv**, instale com o Python dele e sem `--user`. Não instale em ambiente diferente do usado pelo site.
6. Em **Web → Reload**, reinicie `pedroteste.pythonanywhere.com`. Atualize a página com `Ctrl+F5`.

O arquivo `/var/www/pedroteste_pythonanywhere_com_wsgi.py` pode permanecer como está se importa corretamente `from flask_app import app as application` e a pasta `/home/Pedroteste/mysite` já estiver no `sys.path`.

## Instalação nova

1. Extraia o ZIP completo preservando a pasta `mysite/`.
2. Copie `.env.example` para `.env` e crie segredos **diferentes e aleatórios**, com no mínimo 32 caracteres. Na hospedagem HTTPS use `SECURE_COOKIES=true`.
3. Instale as dependências de `requirements.txt` no ambiente do site.
4. Configure a pasta de origem e o WSGI segundo o arquivo `deployment_examples/pythonanywhere_wsgi.py.example` (ajustando o caminho/usuário).
5. Inicialize o site; o SQLite é criado pela aplicação. Não copie dados de demonstração para uma aplicação pública sem conferir que são fictícios.

## Funcionalidades preservadas

- Até 15 fotos (JPG/PNG/WebP) e prévia 4K em posts, com edição visual e texto.
- Imagens e GIFs animados nos comentários.
- Um vídeo MP4/WebM por post, armazenado em pasta privada `data/byfrost_post_videos/`, sujeito ao limite de 64 MiB.
- Até cinco imagens privadas por mensagem, anexos de áudio próprio/autorizado, compartilhamentos e download de posts.
- Login, landing, feed, Stories, perfis públicos, mapas, organizações, doações, mensagens e personalização da versão anterior.

O Flask configura até 160 MiB por requisição, mas o plano ou proxy do PythonAnywhere pode impor um teto menor. Fotos originais têm limite de 18 MiB cada, e GIFs de comentários têm 8 MiB. A infraestrutura e o navegador ainda determinam quais codecs de vídeo podem ser reproduzidos.

**Importante:** a unificação de nomes resolve dependências internas dos módulos de mídia, mas não instala `Flask-Limiter` nem outras bibliotecas externas. Se aparecer `ModuleNotFoundError: flask_limiter`, instale as dependências no ambiente correto.

## Diagnóstico rápido

```bash
cd /home/Pedroteste/mysite
ls -l blueprints/media.py
python3.11 -c "from blueprints.media import jpeg_photo, read_comment_media, store_post_video; print('imports OK')"
python3.11 -c "from flask_app import app; print('Flask OK')"
```

Nenhum código Python incluído neste pacote depende mais de `blueprints.media_v9` nem de `blueprints.media_v10`.
