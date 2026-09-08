-- 0004_seed_vertical_freedom.sql — the first tenant.
--
-- This is the ONLY file in the repository permitted to name Vertical Freedom.
-- Everything the codebase used to hardcode about them — the CORE/WIDE keyword
-- lists, the {ong, sanatate} eligibility gate, the contact address — lives here
-- as one organisation's data.
--
-- The term lists are copied VERBATIM out of funding_radar.CONFIG. They are not
-- re-derived, re-ordered or tidied, because Phase C's acceptance gate is that
-- matching this profile against the warehouse reproduces exactly the call set
-- today's funding_radar.py produces (24 EU, 35-37 adieuronest). Any edit here
-- invalidates that comparison.
--
-- Terms are grouped BY LANGUAGE, not by source. The two lists were calibrated
-- against text in different languages and are not interchangeable: 'screening'
-- is CORE in the Romanian list and WIDE in the English one, and 'animal' as an
-- English context guard is a substring of Romanian 'animală'. Merging them
-- changes what matches, which is why calls carries a `lang` column.

insert into public.organizations (id, name, profile)
values (
  '00000000-0000-4000-8000-000000000001',
  'Vertical Freedom',
  jsonb_build_object(
    'mission',
      'ONG care sprijină pacienții oncologici: terapii complementare și integrative, '
      || 'psihoterapie, sprijin emoțional, nutriție și prevenție.',

    'notification_email', 'office@verticalfreedom.org',

    'notify', jsonb_build_object(
      'weekly_digest', true,
      'deadline_reminders', jsonb_build_array(14, 3)
    ),

    -- The adieuronest applicability gate, verbatim. The live vocabulary of the
    -- `categorii` column is exactly: companii, universitati, autoritati, ong,
    -- persoane, scoli, cultura, sanatate. `sanatate` appears on only 3 of 1162
    -- rows, so `ong` carries this gate.
    'eligible_as', jsonb_build_array('ong', 'sanatate'),

    'geography', jsonb_build_object(
      'countries',    jsonb_build_array('RO'),
      'cross_border', jsonb_build_array('MD', 'UA')
    ),

    'matching', jsonb_build_object(

      -- Romanian: adieuronest and mipe_calendar.
      'ro', jsonb_build_object(
        -- CORE is matched against the full record including the long
        -- eligibility and funding prose.
        'core', jsonb_build_array(
          'cancer', 'oncolog', 'tumor', 'paliativ',
          'terapii complementare', 'terapii alternative', 'terapii integrative',
          'abordare holistica', 'abordare holistă', 'holistic',
          'psihoterapie', 'sprijin emotional', 'sprijin emoțional',
          'sănătate mintal', 'sanatate mintal',
          'pacient', 'screening', 'boli cronice', 'nutriție', 'nutritie'
        ),
        -- WIDE is matched against TITLE AND PROGRAMME ONLY. These words appear
        -- constantly in generic boilerplate ("beneficiarii din domeniul
        -- sănătății pot..."), so full-text matching on them pulled in NetZero
        -- innovation and textile-SME calls. In a title they are signal.
        -- Diacritic and non-diacritic spellings are both listed, and terms are
        -- stems: Romanian inflects, so 'sănătate' does not match 'sănătății'.
        'wide', jsonb_build_array(
          'sănătate', 'sanatate', 'medical', 'spital', 'psiholog',
          'consiliere', 'prevenție', 'preventie', 'incluziune', 'vindecare', 'ong'
        ),
        'guards', jsonb_build_array()
      ),

      -- English: the EU reference dataset.
      'en', jsonb_build_object(
        -- Matched against title + callTitle. Deliberately NOT against `tags`,
        -- which is a ~40-term marketing keyword dump; matching it made
        -- 'mental health' hit a call about eradicating invasive species.
        'core', jsonb_build_array(
          'cancer', 'oncolog', 'tumour', 'palliative', 'psychosocial',
          'psychotherap', 'mental health', 'integrative medicine',
          'complementary medicine', 'patient support', 'patient empowerment',
          'patient-centred', 'cancer survivor', 'caregiver', 'informal carer',
          'health promotion', 'health literacy', 'hospice', 'cancer patients',
          'chronic disease', 'non-communicable disease'
        ),
        -- Matched against the TITLE ONLY, and phrases rather than bare words.
        -- Bare 'health' matches soil, plant, livestock and ecosystem health;
        -- bare 'mental' is a substring of environmental, experimental and
        -- fundamental, which is how a quantum-computing pilot line reached a
        -- cancer-charity digest during calibration.
        'wide', jsonb_build_array(
          'public health', 'human health', 'healthcare', 'health care',
          'health system', 'mental well', 'psycholog', 'wellbeing',
          'well-being', 'social inclusion', 'disease prevention', 'screening'
        ),
        -- A title carrying a WIDE term AND one of these is about something
        -- else. The health vocabulary is shared with agriculture, ecology and
        -- security: "Health of ecosystems and wild species, predictions and
        -- impacts on human health" is a biodiversity call, not a health one.
        'guards', jsonb_build_array(
          'soil', 'plant health', 'animal', 'livestock', 'veterinar',
          'ecosystem', 'crime', 'food waste', 'forest', 'biodivers',
          'wildlife', 'construction', 'renovation', 'footwear', 'vehicle'
        )
      )
    )
  )
)
on conflict (id) do nothing;
