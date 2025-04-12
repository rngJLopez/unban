import logging
import json
import time
import random
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext
from telegram.error import NetworkError, RetryAfter, BadRequest, ChatMigrated

# Configuración
TOKEN = "7975151675:AAGtFG1JU-ttIol2C6MLEOdjze1SKGOzAmU"
CONFIG_FILE = "config.json"
MAX_RETRIES = 3
RETRY_DELAY = 2

# Cargar configuración
def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.error(f"Archivo de configuración {CONFIG_FILE} no encontrado")
        raise
    except json.JSONDecodeError:
        logging.error(f"Error en el formato del archivo {CONFIG_FILE}")
        raise

# Configurar logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Funciones auxiliares
def notify_admins(context, message):
    """Notifica a todos los administradores sobre un evento importante"""
    if 'admins' not in config:
        return
        
    for admin_id in config["admins"]:
        try:
            context.bot.send_message(
                chat_id=admin_id,
                text=f"⚠️ Notificación del Bot:\n{message}"
            )
        except Exception as e:
            logger.error(f"No se pudo notificar al admin {admin_id}: {e}")

def check_connection(bot):
    """Verifica la conexión con los servidores de Telegram"""
    try:
        return bot.get_me() is not None
    except Exception as e:
        logger.error(f"Error verificando conexión: {e}")
        return False

# Handlers de comandos
def start(update: Update, context: CallbackContext):
    """Maneja el comando /start"""
    user_id = update.effective_user.id
    response = (
        f'👋 ¡Hola! Soy un bot para desbanear usuarios en tus canales.\n'
        f'Tu ID de usuario es: {user_id}\n\n'
        f'🔹 Usa /unban <user_id> para desbanear a un usuario\n'
        f'🔹 Usa /id para ver tu ID de usuario\n'
        f'🔹 Usa /status para ver el estado del bot'
    )
    update.message.reply_text(response)

def unban_user(update: Update, context: CallbackContext):
    """Maneja el comando /unban con reintentos y manejo de errores mejorado"""
    admin_id = str(update.effective_user.id)
    
    # Verificar permisos
    if admin_id not in config["admins"]:
        update.message.reply_text("❌ No tienes permisos para usar este bot.")
        return
        
    # Validar argumentos
    if not context.args:
        update.message.reply_text("ℹ️ Uso: /unban <user_id>")
        return
    
    target_user = context.args[0]

    # Validar formato del ID
    if not target_user.lstrip('-').isdigit():
        update.message.reply_text("❌ El user_id debe ser numérico (ej: 123456789).")
        return

    target_user = int(target_user)
    results = []
    success_count = 0
    
    # Procesar cada canal con reintentos
    for channel_data in config["admins"][admin_id]:
        channel_id = channel_data["id"]
        channel_name = channel_data["name"]
        last_error = None
        
        # Verificación previa de estado (opcional)
        try:
            member = context.bot.get_chat_member(chat_id=channel_id, user_id=target_user)
            if member.status != 'kicked':
                results.append(f"ℹ️ Usuario {target_user} no estaba baneado en {channel_name}")
                success_count += 1
                continue
        except Exception:
            pass  # Si falla la verificación, continuamos con el desban
        
        for attempt in range(MAX_RETRIES):
            try:
                context.bot.unban_chat_member(
                    chat_id=channel_id,
                    user_id=target_user
                )
                result_msg = f"✅ Usuario {target_user} desbaneado en {channel_name}"
                results.append(result_msg)
                logger.info(result_msg)
                success_count += 1
                break
                
            except RetryAfter as e:
                wait_time = e.retry_after
                logger.warning(f"Límite de tasa excedido en {channel_name}. Esperando {wait_time} segundos...")
                time.sleep(wait_time)
                continue
                
            except NetworkError as e:
                last_error = f"🔌 Error de red en {channel_name}: {str(e)[:100]}"
                logger.warning(last_error)
                time.sleep(RETRY_DELAY * (attempt + 1))
                continue
                
            except BadRequest as e:
                error_msg = str(e).lower()
                if "user not found" in error_msg or "participant_id_invalid" in error_msg:
                    # Caso exitoso (usuario no estaba baneado)
                    result_msg = f"ℹ️ Usuario {target_user} no estaba baneado en {channel_name}"
                    results.append(result_msg)
                    logger.info(result_msg)
                    success_count += 1
                    break
                elif "not enough rights" in error_msg:
                    last_error = f"🔒 Sin permisos en {channel_name}"
                elif "chat not found" in error_msg:
                    last_error = f"❌ Canal {channel_name} no existe"
                else:
                    last_error = f"❌ Error en {channel_name}: {error_msg[:100]}"
                break
                
            except ChatMigrated as e:
                last_error = f"🔄 El canal {channel_name} ha migrado a nuevo ID: {e.new_chat_id}"
                channel_data["id"] = e.new_chat_id  # Actualizar configuración
                break
                
            except Exception as e:
                last_error = f"❌ Error inesperado en {channel_name}: {str(e)[:100]}"
                break
                
        else:  # Se ejecuta si todos los reintentos fallaron
            if last_error:
                results.append(last_error)
                logger.error(last_error)
            else:
                error_msg = f"❌ Error desconocido en {channel_name} (máx reintentos)"
                results.append(error_msg)
                logger.error(error_msg)

    # Enviar resumen con formato mejorado
    summary = (
        f" Informe usuario {target_user}:\n"
    ) + "\n".join(f"  - {r}" for r in results)
    
    try:
        update.message.reply_text(summary)
    except Exception as e:
        logger.error(f"Error al enviar resumen: {e}")

def get_id(update: Update, context: CallbackContext):
    """Maneja el comando /id"""
    user_id = update.effective_user.id
    update.message.reply_text(
        f"🔍 Tu ID de usuario es: `{user_id}`",
        parse_mode="Markdown"
    )

def status(update: Update, context: CallbackContext):
    """Maneja el comando /status"""
    admin_id = str(update.effective_user.id)
    if admin_id not in config["admins"]:
        update.message.reply_text("❌ Solo los administradores pueden ver el estado.")
        return
    
    status_msg = (
        "🟢 Bot operativo\n\n"
        f"• Canales configurados: {sum(len(channels) for channels in config['admins'].values())}\n"
        f"• Administradores: {len(config['admins'])}\n"
        f"• Versión Python: 3.11\n"
        f"• Última actualización: 2025-04-05"
    )
    update.message.reply_text(status_msg)

def error_handler(update: Update, context: CallbackContext):
    """Maneja errores no capturados"""
    error = context.error
    logger.error(f'Error no capturado: {error}', exc_info=error)
    
    if isinstance(error, NetworkError):
        logger.warning("Problema de red detectado")
        notify_admins(context, "⚠️ Problema de red detectado")
    elif isinstance(error, RetryAfter):
        logger.warning(f"Demasiadas solicitudes. Esperando {error.retry_after} segundos")
    elif isinstance(error, BadRequest):
        logger.warning(f"Solicitud incorrecta: {error}")
    elif update:
        try:
            update.message.reply_text(f"❌ Ocurrió un error: {str(error)[:200]}")
        except:
            pass

def main():
    try:
        global config
        config = load_config()
        
        # Configuración de conexión compatible con v13.x
        request_kwargs = {
            'read_timeout': 20,
            'connect_timeout': 20
        }
        
        updater = Updater(
            TOKEN,
            use_context=True,
            request_kwargs=request_kwargs
        )
        
        dp = updater.dispatcher
        dp.add_error_handler(error_handler)

        # Comandos
        dp.add_handler(CommandHandler("start", start))
        dp.add_handler(CommandHandler("id", get_id))
        dp.add_handler(CommandHandler("unban", unban_user))
        dp.add_handler(CommandHandler("status", status))

        logger.info("Iniciando bot...")
        
        # Verificar conexión inicial
        if not check_connection(updater.bot):
            logger.error("No se pudo establecer conexión inicial con Telegram")
            notify_admins(updater.bot, "🔴 No se pudo conectar a Telegram")
            return

        # Bucle principal con reconexión automática
        while True:
            try:
                logger.info("Bot en funcionamiento...")
                updater.start_polling(
                    timeout=30,
                    poll_interval=1,
                    drop_pending_updates=True
                )
                updater.idle()
            except NetworkError as e:
                wait_time = random.uniform(1, 5)
                logger.warning(f"Error de red: {e}. Reintentando en {wait_time:.1f} segundos...")
                time.sleep(wait_time)
            except RetryAfter as e:
                logger.warning(f"Límite de tasa excedido: {e}. Esperando {e.retry_after} segundos...")
                time.sleep(e.retry_after)
            except Exception as e:
                logger.error(f"Error inesperado: {e}")
                notify_admins(updater.bot, f"🔴 Error crítico: {str(e)[:200]}")
                time.sleep(5)
                
    except Exception as e:
        logger.error(f"Error al iniciar el bot: {e}")
        raise

if __name__ == '__main__':
    main()