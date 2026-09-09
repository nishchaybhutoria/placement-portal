"""Import every vertical-slice model so Base.metadata is complete."""

from app.modules.admin import models as admin_models
from app.modules.analytics import models as analytics_models
from app.modules.applications import models as application_models
from app.modules.companies import models as company_models
from app.modules.cycles import models as cycle_models
from app.modules.discipline import models as discipline_models
from app.modules.identity import models as identity_models
from app.modules.jobs import models as job_models
from app.modules.notifications import models as notification_models
from app.modules.offers import models as offer_models
from app.modules.overrides import models as override_models
from app.modules.profiles import models as profile_models
from app.modules.taxonomies import models as taxonomy_models

MODEL_MODULES = (
    admin_models,
    analytics_models,
    application_models,
    company_models,
    cycle_models,
    discipline_models,
    identity_models,
    job_models,
    notification_models,
    offer_models,
    override_models,
    profile_models,
    taxonomy_models,
)

