-- The job cost module assessment: what each module setting was found to be and
-- the gap it left, from the engagement's configuration review.

select module, setting, as_found, gap, resolved_by
from {{ ref('stg_remediation__config_gap_list') }}
