{#- Use the custom +schema name as-is (olist_staging / olist_marts)
    instead of dbt's default "<target_dataset>_<custom_schema>". -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
