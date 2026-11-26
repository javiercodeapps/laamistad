from . import models

def post_init_hook(env):
    """Initialize AFIP service monitors after module installation"""
    env['afip.service.status'].sudo().initialize_services()
