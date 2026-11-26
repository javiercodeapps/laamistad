# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [19.0.1.2.0] - 2026-07-13

### Changed
- AFIP caído ya NO bloquea la facturación cuando hay contingencia CAEA
  disponible (`l10n_ar_caea` instalado, company habilitada, CAEA vigente
  y diario de contingencia mapeado): se señaliza y se deja pasar para
  que `l10n_ar_caea` re-rutee al PV exclusivo CAEA (RG 5785/2025).
- Los diarios PV exclusivo CAEA (`l10n_ar_afip_pos_caea`) se saltean el
  check por completo: emiten offline por diseño.
- Sin dependencia nueva: si `l10n_ar_caea` no está instalado, el
  comportamiento clásico (bloquear) se mantiene intacto.

## [18.0.1.0.0] - 2024-12-03

### Added
- Initial release for Odoo 18
- AFIP/ARCA WebService monitoring (WSFE and WSAA)
- Automatic service status checking every 5 minutes
- Red warning banner when service is unavailable
- Invoice confirmation blocking for Argentinian POS journals when service is down
- Manual service status verification
- Configuration settings for environment (Testing/Production)
- Configurable timeout and check intervals
- Option to enable/disable invoice blocking
- Option to show/hide warning banner
- Kanban, Tree, and Form views for service status
- Configuration menu in Accounting settings
- Status button in invoice form for POS journals
- Success banner when service is available
- Cron job for automatic monitoring
- Unit tests for all main functionalities
- Support for Docker and Docker Swarm deployment
- Comprehensive documentation (README, INSTALL, QUICKSTART)

### Features
- **Automatic Monitoring**: Checks AFIP services every 5 minutes
- **Visual Alerts**: Red banner with animation when service is down
- **Smart Blocking**: Only blocks invoices with `l10n_ar_is_pos = True`
- **Flexible Configuration**: Environment, timeout, interval, blocking, and banner options
- **Manual Verification**: Refresh button for on-demand status checks
- **Error Details**: Shows detailed error messages and consecutive failures
- **Responsive Design**: Mobile-friendly banner and views
- **Performance**: Uses zeep and requests libraries for optimal performance

### Technical Details
- Compatible with Odoo 18
- Uses OWL (Odoo Web Library) for frontend components
- Post-init hook for automatic service initialization
- Proper inheritance of account.move and res.config.settings models
- Security rules for different user groups
- Comprehensive error handling
- Logging of all status checks

### Dependencies
- odoo >= 18.0
- account module
- l10n_ar (Argentinian Localization)
- Python: requests >= 2.31.0, zeep >= 4.2.1, lxml >= 4.9.0

### Security
- User: Read-only access to service status
- Account Manager: Full access to service configuration
- System Administrator: Complete control

### Documentation
- README.md: Complete user documentation
- INSTALL.md: Detailed installation guide with Docker examples
- QUICKSTART.md: Quick reference guide
- Inline code documentation
- Unit tests with examples

## Future Enhancements (Planned)

### [18.0.1.1.0] - TBD
- [ ] Email notifications when service goes down
- [ ] Dashboard widget with service status
- [ ] Historical service availability charts
- [ ] Export service status reports
- [ ] Webhook notifications
- [ ] SMS alerts option

### [18.0.1.2.0] - TBD
- [ ] Support for more AFIP services (WSR, WSCDC, etc.)
- [ ] API for external monitoring tools
- [ ] Custom retry strategies
- [ ] Load balancing for multiple AFIP endpoints
- [ ] Predictive service downtime analysis

### [18.0.2.0.0] - TBD
- [ ] Integration with other Argentinian fiscal modules
- [ ] Advanced reporting and analytics
- [ ] Multi-company support improvements
- [ ] Custom alert rules engine

## Known Issues

### Version 18.0.1.0.0
- None reported yet

## Breaking Changes

### Version 18.0.1.0.0
- None (initial release)

## Upgrade Guide

### To 18.0.1.0.0
- Initial installation, no upgrade needed

## Support and Contribution

For bug reports, feature requests, or contributions:
- Check existing issues in the repository
- Create detailed bug reports with logs
- Submit pull requests with tests
- Update documentation for new features

## License

LGPL-3

## Credits

Developed for Odoo 18
Compatible with Argentinian localization (l10n_ar)

---

[Unreleased]: https://github.com/yourcompany/afip_webservice_monitor/compare/v18.0.1.0.0...HEAD
[18.0.1.0.0]: https://github.com/yourcompany/afip_webservice_monitor/releases/tag/v18.0.1.0.0
