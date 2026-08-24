-- The actions the owner decided on the diagnostic's findings, taken and not taken,
-- with who decided, when and, for those not taken, the reason. Grain: action.

select * from {{ ref('stg_remediation__engagement_actions') }}
