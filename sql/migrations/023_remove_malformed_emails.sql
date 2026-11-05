-- Mistyped mailto links, such as info@southwest, were saved as emails. Those
-- leads go back to the call list until a real address is found.

begin;

update website_enrichment
set emails_found = array(
        select e
        from unnest(emails_found) with ordinality as found(e, position)
        where e ~* '^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$'
        order by position
    )
where exists (
    select 1
    from unnest(emails_found) as e
    where e !~* '^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$'
);

commit;
