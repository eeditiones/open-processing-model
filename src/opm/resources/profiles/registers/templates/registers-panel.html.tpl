[#
  The register panel. With categories, one tab per category that has
  entries (fragment register_<category>), as radio buttons and labels so it
  works without scripts; a single category is shown without tabs. Without
  categories, the "register" fragment.
#]
[% let $settings = $context?features?register %]
[% let $categories = $settings?categories?*[$context?fragments?('register_' || .)] %]
[% let $single = if (exists($categories)) then () else $context?fragments?register %]
[% if exists($categories) or $single %]
<section class="register-panel" aria-label="[[ ($settings?label[. != ''], 'Register')[1] ]]">
  [% if $settings?label != '' and count($categories) le 1 %]
  <h2 class="register-panel__title">[[ $settings?label ]]</h2>
  [% endif %]
  [% if count($categories) gt 1 %]
  <div class="register-tabs">
    [% for $category in $categories %]
    [% let $id = 'register-tab-' || $category %]
    [% let $label = ($settings?category_labels?($category), upper-case(substring($category, 1, 1)) || substring($category, 2))[1] %]
    <input type="radio" name="register-tab" id="[[ $id ]]" class="register-tabs__radio"[% if $category = $categories[1] %] checked[% endif %] autocomplete="off">
    <label for="[[ $id ]]" class="register-tabs__tab">[[ $label ]]</label>
    <div class="register-tabs__panel" data-label="[[ $label ]]">
      [[ $context?fragments?('register_' || $category) ]]
    </div>
    [% endlet %][% endlet %]
    [% endfor %]
  </div>
  [% elif exists($categories) %]
  [[ $context?fragments?('register_' || $categories) ]]
  [% else %]
  [[ $single ]]
  [% endif %]
</section>
[% endif %]
[% endlet %][% endlet %][% endlet %]
