<?xml version="1.0" encoding="UTF-8"?>

<xsl:stylesheet version="1.0"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
    xmlns:mods="http://www.loc.gov/mods/v3"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:jats="http://www.ncbi.nlm.nih.gov/JATS1">

    <xsl:output method="xml" indent="yes" encoding="UTF-8"/>
    <xsl:param name="currentDateTime" select="'1970-01-01T00:00:00'"/> <!-- Default value -->
    <xsl:param name="genreOverride" select="''"/> <!-- Optional: 'dissertation', 'report', 'book' (monograph), or 'coll' (edited_book) to override mods:genre -->
    <xsl:param name="depositorName" select="'malmo:malmo'"/> <!-- Depositor name from CROSSREF_DEPOSITOR_NAME -->
    <xsl:param name="depositorEmail" select="'depositor@example.com'"/> <!-- Depositor email from CROSSREF_EMAIL -->

    <xsl:template match="/">  
        <!-- Use the 'mods' prefix in the XPath -->
        <xsl:apply-templates select="mods:modsCollection"/>
        <doi_batch xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
            xsi:schemaLocation="http://www.crossref.org/schema/5.4.0 https://www.crossref.org/schemas/crossref5.4.0.xsd"
            xmlns="http://www.crossref.org/schema/5.4.0" 
            xmlns:jats="http://www.ncbi.nlm.nih.gov/JATS1"
            xmlns:fr="http://www.crossref.org/fundref.xsd" 
            xmlns:mml="http://www.w3.org/1998/Math/MathML"
            version="5.4.0">
            <head>
                <doi_batch_id>mau<xsl:value-of select="$currentDateTime"/></doi_batch_id>
                <timestamp> <xsl:value-of select="$currentDateTime"/></timestamp>
                <depositor>
                    <depositor_name><xsl:value-of select="$depositorName"/></depositor_name>
                    <email_address><xsl:value-of select="$depositorEmail"/></email_address>
                </depositor>
                <registrant>
                <xsl:choose>
                    <xsl:when test="mods:genre[@authority='kev'] = 'dissertation'">
                        <xsl:text>Malmö University Press</xsl:text>
                    </xsl:when>
                    <xsl:otherwise>
                        <xsl:text>Malmö University</xsl:text>
                    </xsl:otherwise>
                </xsl:choose>
                </registrant>
            </head>
            <body>
            <!-- Use the 'mods' prefix in the XPath -->
            <xsl:for-each select="mods:modsCollection/mods:mods">
                <xsl:apply-templates select="mods:modsCollection/mods:mods"/>
                <xsl:choose>
                    <xsl:when test="$genreOverride = 'dissertation' or ($genreOverride = '' and mods:genre[@authority='kev'] = 'dissertation')">
                        <dissertation publication_type="full_text" xmlns="http://www.crossref.org/schema/5.4.0">
                        <xsl:call-template name="emit-language-attribute">
                            <xsl:with-param name="lang" select="mods:titleInfo/@lang"/>
                        </xsl:call-template>
                            <contributors xmlns="http://www.crossref.org/schema/5.4.0">
                                <xsl:call-template name="render-contributors">
                                    <xsl:with-param name="roleTerm" select="'aut'"/>
                                    <xsl:with-param name="contributorRole" select="'author'"/>
                                </xsl:call-template>
                                <xsl:call-template name="render-contributors">
                                    <xsl:with-param name="roleTerm" select="'edt'"/>
                                    <xsl:with-param name="contributorRole" select="'editor'"/>
                                </xsl:call-template>
                            </contributors>                             
                            <xsl:call-template name="render-titles"/>
                            <xsl:call-template name="render-abstracts"/>
                            <approval_date xmlns="http://www.crossref.org/schema/5.4.0">
                                <xsl:if test="mods:originInfo/mods:dateOther[@type='defence']">
                                    <month>
                                        <xsl:value-of select="substring(mods:originInfo/mods:dateOther[@type='defence'], 6, 2)"/>
                                    </month>
                                    <day>
                                        <xsl:value-of select="substring(mods:originInfo/mods:dateOther[@type='defence'], 9, 2)"/>
                                    </day>
                                </xsl:if>
                                <year>
                                    <xsl:choose>
                                        <xsl:when test="mods:originInfo/mods:dateOther[@type='defence']">
                                            <xsl:value-of select="substring(mods:originInfo/mods:dateOther[@type='defence'], 1, 4)"/>
                                        </xsl:when>
                                        <xsl:otherwise>
                                            <xsl:value-of select="mods:originInfo/mods:dateIssued"/>
                                        </xsl:otherwise>
                                    </xsl:choose>
                                </year>
                            </approval_date> 
                                <institution xmlns="http://www.crossref.org/schema/5.4.0">
                                <institution_name>
                                    <xsl:value-of select="mods:name[mods:role/mods:roleTerm='aut']/mods:affiliation[1]"/>
                                </institution_name>
                                <xsl:if test="contains(., 'Malmö University') or contains(., 'Malmö universitet')">
                                    <institution_id type="ror">https://ror.org/05wp7an13</institution_id>
                                    <institution_id type="isni">https://isni.org/isni/0000000099619487</institution_id>
                                    <institution_id type="wikidata">https://www.wikidata.org/wiki/Q977781</institution_id>
                                </xsl:if>
                            </institution>
                            <degree xmlns="http://www.crossref.org/schema/5.4.0">
                            <xsl:choose>
                                <xsl:when test="contains(mods:genre[@type='publicationTypeCode'], 'DoctoralThesis')">
                                    <xsl:text>Doctoral thesis</xsl:text>
                                </xsl:when>
                                <xsl:when test="contains(mods:genre[@type='publicationTypeCode'], 'LicentiateThesis')">
                                    <xsl:text>Licentiate thesis</xsl:text>
                                </xsl:when>
                            </xsl:choose>
                            </degree> 
                            <xsl:call-template name="render-isbn"/>
                            <xsl:call-template name="render-doi-data"/>
                        </dissertation>
                    </xsl:when>
                    <xsl:when test="$genreOverride = 'report' or ($genreOverride = '' and mods:genre[@type='publicationTypeCode'] = 'report')">
                    <report-paper xmlns="http://www.crossref.org/schema/5.4.0">
                        <xsl:choose>
                        <xsl:when test="mods:relatedItem/mods:identifier[@type='issn']">
                        <report-paper_series_metadata xmlns="http://www.crossref.org/schema/5.4.0">
                        <xsl:call-template name="emit-language-attribute">
                            <xsl:with-param name="lang" select="mods:titleInfo/@lang"/>
                        </xsl:call-template>
                            <series_metadata xmlns="http://www.crossref.org/schema/5.4.0">
                                <titles>
                                    <title>
                                        <xsl:value-of select="mods:relatedItem/mods:titleInfo/mods:title"/>
                                    </title>
                                </titles>
                                <issn>
                                    <xsl:value-of select="mods:relatedItem/mods:identifier[@type='issn']"/>
                                </issn>
                            </series_metadata>    
                            <contributors xmlns="http://www.crossref.org/schema/5.4.0">
                                <xsl:call-template name="render-contributors">
                                    <xsl:with-param name="roleTerm" select="'aut'"/>
                                    <xsl:with-param name="contributorRole" select="'author'"/>
                                </xsl:call-template>
                                <xsl:call-template name="render-contributors">
                                    <xsl:with-param name="roleTerm" select="'edt'"/>
                                    <xsl:with-param name="contributorRole" select="'editor'"/>
                                </xsl:call-template>
                            </contributors> 
                            <xsl:call-template name="render-titles"/>
                            <xsl:call-template name="render-abstracts"/>
                            <publication_date xmlns="http://www.crossref.org/schema/5.4.0">
                                <year><xsl:value-of select="mods:originInfo/mods:dateIssued"/></year>
                            </publication_date>
                            <xsl:call-template name="render-isbn"/>
                            <xsl:call-template name="render-publisher"/>
                            <xsl:call-template name="render-doi-data"/>
                        </report-paper_series_metadata>
                        </xsl:when>
                        <xsl:otherwise> 
                        <report-paper_metadata xmlns="http://www.crossref.org/schema/5.4.0">
                            <xsl:call-template name="emit-language-attribute">
                                <xsl:with-param name="lang" select="mods:titleInfo/@lang"/>
                            </xsl:call-template>    
                            <contributors>
                                <xsl:call-template name="render-contributors">
                                    <xsl:with-param name="roleTerm" select="'aut'"/>
                                    <xsl:with-param name="contributorRole" select="'author'"/>
                                </xsl:call-template>
                                <xsl:call-template name="render-contributors">
                                    <xsl:with-param name="roleTerm" select="'edt'"/>
                                    <xsl:with-param name="contributorRole" select="'editor'"/>
                                </xsl:call-template>
                            </contributors>
                            <xsl:call-template name="render-titles"/>
                            <xsl:call-template name="render-abstracts"/>
                            <publication_date xmlns="http://www.crossref.org/schema/5.4.0">
                                <year><xsl:value-of select="mods:originInfo/mods:dateIssued"/></year>
                            </publication_date>
                            <xsl:call-template name="render-isbn"/>
                            <xsl:call-template name="render-publisher"/>
                            <xsl:call-template name="render-doi-data"/>
                        </report-paper_metadata>
                        </xsl:otherwise>
                        </xsl:choose> 
                    </report-paper>                         
                </xsl:when>
                <xsl:when test="$genreOverride = 'book' or $genreOverride = 'coll' or ($genreOverride = '' and mods:genre[@authority='kev'] = 'book')">
                    <book xmlns="http://www.crossref.org/schema/5.4.0">
                        <xsl:attribute name="book_type">
                            <xsl:choose>
                                <xsl:when test="$genreOverride = 'coll'">edited_book</xsl:when>
                                <xsl:when test="$genreOverride = 'book'">monograph</xsl:when>
                                <xsl:when test="$genreOverride = '' and mods:genre[@authority='svep'] = 'sam'">edited_book</xsl:when>
                                <xsl:otherwise>monograph</xsl:otherwise>
                            </xsl:choose>
                        </xsl:attribute>
                        <xsl:choose>
                        <xsl:when test="mods:relatedItem/mods:identifier[@type='issn']">
                        <book_series_metadata xmlns="http://www.crossref.org/schema/5.4.0">
                            <series_metadata xmlns="http://www.crossref.org/schema/5.4.0">
                                <titles>
                                    <title>
                                        <xsl:value-of select="mods:relatedItem/mods:titleInfo/mods:title"/>
                                    </title>
                                </titles>
                                <issn>
                                    <xsl:value-of select="mods:relatedItem/mods:identifier[@type='issn']"/>
                                </issn>
                            </series_metadata>    
                            <contributors xmlns="http://www.crossref.org/schema/5.4.0">
                                <xsl:call-template name="render-contributors">
                                    <xsl:with-param name="roleTerm" select="'aut'"/>
                                    <xsl:with-param name="contributorRole" select="'author'"/>
                                </xsl:call-template>
                                <xsl:call-template name="render-contributors">
                                    <xsl:with-param name="roleTerm" select="'edt'"/>
                                    <xsl:with-param name="contributorRole" select="'editor'"/>
                                </xsl:call-template>
                            </contributors> 
                            <xsl:call-template name="render-titles"/>
                            <xsl:call-template name="render-abstracts"/>
                            <publication_date xmlns="http://www.crossref.org/schema/5.4.0">
                                <year><xsl:value-of select="mods:originInfo/mods:dateIssued"/></year>
                            </publication_date>
                            <xsl:call-template name="render-isbn"/>
                            <xsl:call-template name="render-publisher"/>
                            <xsl:call-template name="render-doi-data"/>
                        </book_series_metadata>
                        </xsl:when>
                        <xsl:otherwise>
                        <book_metadata xmlns="http://www.crossref.org/schema/5.4.0">
                        <xsl:call-template name="emit-language-attribute">
                            <xsl:with-param name="lang" select="mods:titleInfo/@lang"/>
                        </xsl:call-template>    
                        <contributors xmlns="http://www.crossref.org/schema/5.4.0">
                            <xsl:call-template name="render-contributors">
                                <xsl:with-param name="roleTerm" select="'aut'"/>
                                <xsl:with-param name="contributorRole" select="'author'"/>
                            </xsl:call-template>
                            <xsl:call-template name="render-contributors">
                                <xsl:with-param name="roleTerm" select="'edt'"/>
                                <xsl:with-param name="contributorRole" select="'editor'"/>
                            </xsl:call-template>
                        </contributors>
                        <xsl:call-template name="render-titles"/>
                        <xsl:call-template name="render-abstracts"/>
                        <publication_date xmlns="http://www.crossref.org/schema/5.4.0">
                            <year><xsl:value-of select="mods:originInfo/mods:dateIssued"/></year>
                        </publication_date>
                        <xsl:call-template name="render-isbn"/>
                        <xsl:call-template name="render-publisher"/>
                        <xsl:call-template name="render-doi-data"/>
                    </book_metadata> 
                    </xsl:otherwise>
                    </xsl:choose>  
                </book>
                </xsl:when>
                </xsl:choose> 
            </xsl:for-each>    
            </body>
         </doi_batch>      
    </xsl:template>     

<xsl:template name="emit-language-attribute">
    <xsl:param name="lang"/>
    <xsl:if test="$lang = 'eng' or 
                  $lang = 'swe' or 
                  $lang = 'nor' or 
                  $lang = 'dan' or 
                  $lang = 'fin' or 
                  $lang = 'deu' or 
                  $lang = 'nld' or 
                  $lang = 'spa' or 
                  $lang = 'ita' or 
                  $lang = 'por' or 
                  $lang = 'rus' or 
                  $lang = 'fra' or 
                  $lang = 'ara'">
        <xsl:attribute name="language">
            <xsl:choose>
                <xsl:when test="$lang = 'eng'">en</xsl:when>
                <xsl:when test="$lang = 'swe'">sv</xsl:when>
                <xsl:when test="$lang = 'nor'">no</xsl:when>
                <xsl:when test="$lang = 'dan'">da</xsl:when>
                <xsl:when test="$lang = 'fin'">fi</xsl:when>
                <xsl:when test="$lang = 'deu'">de</xsl:when>
                <xsl:when test="$lang = 'nld'">nl</xsl:when>
                <xsl:when test="$lang = 'spa'">es</xsl:when>
                <xsl:when test="$lang = 'ita'">it</xsl:when>
                <xsl:when test="$lang = 'por'">pt</xsl:when>
                <xsl:when test="$lang = 'rus'">ru</xsl:when>
                <xsl:when test="$lang = 'fra'">fr</xsl:when>
                <xsl:when test="$lang = 'ara'">ar</xsl:when>
            </xsl:choose>
        </xsl:attribute>
    </xsl:if>
</xsl:template>

<xsl:template name="render-contributors">
    <xsl:param name="roleTerm"/>
    <xsl:param name="contributorRole"/>
    <xsl:for-each select="mods:name/mods:role[mods:roleTerm=$roleTerm]">
        <person_name contributor_role="{$contributorRole}" xmlns="http://www.crossref.org/schema/5.4.0">
            <xsl:attribute name="sequence">
                <xsl:choose>
                    <xsl:when test="position() = 1">first</xsl:when>
                    <xsl:otherwise>additional</xsl:otherwise>
                </xsl:choose>
            </xsl:attribute>
            <given_name>
                <xsl:value-of select="../mods:namePart[@type='given']"/>
            </given_name>
            <surname>
                <xsl:value-of select="../mods:namePart[@type='family']"/>
            </surname>
            <affiliations>
                <xsl:for-each select="../mods:affiliation">
                    <institution>
                        <institution_name>
                            <xsl:value-of select="."/>
                        </institution_name>
                        <xsl:if test="contains(., 'Malmö University') or contains(., 'Malmö universitet')">
                            <institution_id type="ror">https://ror.org/05wp7an13</institution_id>
                            <institution_id type="isni">https://isni.org/isni/0000000099619487</institution_id>
                            <institution_id type="wikidata">https://www.wikidata.org/wiki/Q977781</institution_id>
                        </xsl:if>
                    </institution>        
                </xsl:for-each>
            </affiliations>
            <xsl:if test="contains(../mods:description,'orcid.org')">
                <xsl:variable name="orcid" select="substring-after(../mods:description, 'orcid.org=')"/>
                <ORCID>https://orcid.org/<xsl:value-of select="$orcid"/></ORCID>
            </xsl:if>
        </person_name>                                
    </xsl:for-each>
</xsl:template>

<xsl:template name="render-titles">
    <titles xmlns="http://www.crossref.org/schema/5.4.0">
        <title> 
             <xsl:call-template name="strip-html">
                <xsl:with-param name="text" select="mods:titleInfo/mods:title"/>
            </xsl:call-template>
        </title>
        <xsl:if test="mods:titleInfo/mods:subTitle">
            <subtitle>
                <xsl:call-template name="strip-html">
                    <xsl:with-param name="text" select="mods:titleInfo/mods:subTitle"/>
                </xsl:call-template>
            </subtitle>
        </xsl:if>
    </titles>
</xsl:template>

<xsl:template name="render-isbn">
    <xsl:if test="mods:identifier[@type='isbn' and @displayLabel='electronic']">
        <isbn xmlns="http://www.crossref.org/schema/5.4.0">
            <xsl:value-of select="translate(mods:identifier[@type='isbn' and @displayLabel='electronic'], '-', '')"/>
        </isbn>
    </xsl:if>
</xsl:template>

<xsl:template name="render-publisher">
    <xsl:if test="mods:originInfo/mods:publisher">
        <publisher xmlns="http://www.crossref.org/schema/5.4.0">
            <publisher_name><xsl:value-of select="mods:originInfo/mods:publisher"/></publisher_name>
        </publisher>
    </xsl:if>
</xsl:template>

<xsl:template name="render-doi-data">
    <doi_data xmlns="http://www.crossref.org/schema/5.4.0">
        <doi><xsl:value-of select="mods:identifier[@type='doi']"/></doi>
        <resource><xsl:value-of select="mods:identifier[@type='uri']"/></resource>
        <xsl:if test="mods:location/mods:url[@displayLabel='fulltext']">
           <collection property="crawler-based">
                <item crawler="similarity-check">
                    <resource><xsl:value-of select="mods:location/mods:url[@displayLabel='fulltext']"/></resource>
                </item>                                   
            </collection> 
        </xsl:if>                                  
    </doi_data>
</xsl:template>

<xsl:template name="render-abstracts">
    <xsl:param name="abstracts" select="mods:abstract"/>
    <xsl:for-each select="$abstracts">
        <jats:abstract>
            <xsl:if test="./@lang = 'eng' or 
                          ./@lang = 'swe' or 
                          ./@lang = 'nor' or 
                          ./@lang = 'dan' or 
                          ./@lang = 'fin' or 
                          ./@lang = 'deu' or 
                          ./@lang = 'nld' or 
                          ./@lang = 'spa' or 
                          ./@lang = 'ita' or 
                          ./@lang = 'por' or 
                          ./@lang = 'rus' or 
                          ./@lang = 'fra' or 
                          ./@lang = 'ara'">
                <xsl:attribute name="xml:lang">
                    <xsl:choose>
                        <xsl:when test="./@lang = 'eng'">en</xsl:when>
                        <xsl:when test="./@lang = 'swe'">sv</xsl:when>
                        <xsl:when test="./@lang = 'nor'">no</xsl:when>
                        <xsl:when test="./@lang = 'dan'">da</xsl:when>
                        <xsl:when test="./@lang = 'fin'">fi</xsl:when>
                        <xsl:when test="./@lang = 'deu'">de</xsl:when>
                        <xsl:when test="./@lang = 'nld'">nl</xsl:when>
                        <xsl:when test="./@lang = 'spa'">es</xsl:when>
                        <xsl:when test="./@lang = 'ita'">it</xsl:when>
                        <xsl:when test="./@lang = 'por'">pt</xsl:when>
                        <xsl:when test="./@lang = 'rus'">ru</xsl:when>
                        <xsl:when test="./@lang = 'fra'">fr</xsl:when>
                        <xsl:when test="./@lang = 'ara'">ar</xsl:when>
                    </xsl:choose>
                </xsl:attribute>
            </xsl:if>
            <xsl:choose>
                <xsl:when test="starts-with(., '&lt;p&gt;')">
                    <xsl:call-template name="process-paragraphs">
                        <xsl:with-param name="text" select="." />
                    </xsl:call-template>
                </xsl:when>
                <xsl:otherwise>
                    <xsl:variable name="cleaned" select="normalize-space(translate(., '&#160;', ' '))" />
                    <xsl:if test="$cleaned != ''">
                        <jats:p>
                            <xsl:value-of select="$cleaned" />
                        </jats:p>
                    </xsl:if>
                </xsl:otherwise>
            </xsl:choose>
        </jats:abstract>
    </xsl:for-each>
</xsl:template>

<xsl:template name="strip-html">
    <xsl:param name="text"/>
    <xsl:choose>
        <!-- Match and remove the first HTML tag -->
        <xsl:when test="contains($text, '&lt;')">
            <xsl:variable name="stripped" select="concat(substring-before($text, '&lt;'), substring-after($text, '&gt;'))"/>
            <xsl:call-template name="strip-html">
                <xsl:with-param name="text" select="$stripped"/>
            </xsl:call-template>
        </xsl:when>
        <!-- Output the cleaned text -->
        <xsl:otherwise>
            <xsl:value-of select="$text"/>
        </xsl:otherwise>
    </xsl:choose>
</xsl:template>

<xsl:template name="process-paragraphs">
    <xsl:param name="text" />
    <xsl:choose>
        <!-- Check if there is a paragraph to process -->
        <xsl:when test="contains($text, '&lt;p&gt;')">
            <xsl:variable name="current-paragraph" select="substring-before(substring-after($text, '&lt;p&gt;'), '&lt;/p&gt;')" />
            <xsl:variable name="trimmed" select="normalize-space(translate($current-paragraph, '&#160;', ' '))" />
            <xsl:if test="$trimmed != ''">
                <jats:p>
                    <xsl:value-of select="$trimmed" />
                </jats:p>
            </xsl:if>
            <!-- Process the remaining text -->
            <xsl:call-template name="process-paragraphs">
                <xsl:with-param name="text" select="substring-after($text, '&lt;/p&gt;')" />
            </xsl:call-template>
        </xsl:when>
    </xsl:choose>
</xsl:template>

<xsl:template match="*|@*">
</xsl:template>

</xsl:stylesheet>