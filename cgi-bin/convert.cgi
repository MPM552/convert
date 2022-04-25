#!/usr/bin/perl  -T

=head1 SYNOPSYS

convert 

Web-based interface to my convert.pl program, but entirely inline.

Author: Raphael Finkel 1/2015 © GPL
Version 2.1
	11/2020
	API to ExchangeRate-API changed.  We now grab all currencies and store in
	the file currency.txt, updating if it is more than a day old.

Version 2.0
	Changes from version 1.0:

		Based on ideas from a CS499 project, Spring 2017, by Ronnel Turner, Clay
		Marshall, and Seifalla Moustafa, supervised by Paul Piwowarski:

				Added dimension of currency with immediate lookup.

				Added hint buttons for units, with submenus.

				Added dimension output

		Provided better error message for conversion failure.

		Employed bootstrap and jQuery for formatting output.

		Output now intercalates requests and responses.


=cut

use strict;
use utf8;
use Data::Dumper;
use LWP::UserAgent qw( );
use LWP::ConnCache;
use HTML::Template;
use CGI qw/:standard -debug/;
$ENV{'PATH'} = '/bin:/usr/bin:/usr/local/bin:/usr/local/gnu/bin'; # for security

# constants

my $HTMLtemplateFile = 'convert.tmpl';
# mass, distance, time, current, luminosity, count, temperature
# dimension symbols: mass, length, time, current, luminosity, 
	# number, temperature
my @names = ('x', 'kg', 'm', 's', 'A', 'cd', 'mol', "°K", "USD");
my @dims = ('', 'mass', 'length', 'time', 'current', 'luminosity', 'count', "temperature", 'currency');
my $zero = [0.0,0,0,0,0,0,0,0,0];
my $bad = ['NaN',"",0,0,0,0,0,0,0]; # The first dim holds an error string
my %constants = (
	g   => [1.0, 1,0,0,0,0,0,0,0],
	m   => [1.0, 0,1,0,0,0,0,0,0],
	s   => [1.0, 0,0,1,0,0,0,0,0],
	A   => [1.0, 0,0,0,1,0,0,0,0],
	cd  => [1.0, 0,0,0,0,1,0,0,0],  # candela
	mol => [1.0, 0,0,0,0,0,1,0,0],
	K   => [1.0, 0,0,0,0,0,0,1,0],
	USD => [1.0, 0,0,0,0,0,0,0,1],
);
my %cNames = (
	s => 'second',
	m => 'meter',
	g => 'gram',
	A => 'Ampere',
	cd => 'candela',
	mol => 'mole',
	K => 'degree Kelvin',
	USD => 'United States Dollar',
);
my %multipliers = (
	P => 1e+15, # peta-
	T => 1e+12, # tera-
	G => 1e+9, # giga-
	M => 1e+6, # mega-
	k => 1000.0,  # kilo-
	h => 100.0,   # hecto-
	d => 0.1, 	# deci-
	c => 0.01,  # centi-
	m => 0.001, # milli-
	μ => 1e-06, # micro-
	n => 1e-09, # nano-
	p => 1e-12, # pico-
	f => 1e-15, # femto-
);
my $privateKey = 'ea7060abeba5b76d10838aee';
my $currencyFile = '~/currency.txt';

# variables
my ($connector, # to get currency values
	$HTML, # for HTML::Template
	@resultHTML, # for HTML::Template
	%variables, # user-defined variables
);

# standard units (for drop-down menu)
my %standardUnits = (
	area => [],
	currency => [],
	distance => ['m'],
	electromagnetic => ['A'],
	energy => [],
	force => [],
	mass => ['g'],
	power => [],
	pressure => [],
	time => ['s'],
	velocity => [],
	volume => [],
); # standardUnits
# push @{$standardUnits{'distance'}}, 'm';

sub init {
	my ($title);
	binmode STDOUT, ":utf8";
	binmode STDERR, ":utf8";
	binmode STDIN, ":utf8";
	$title = 'Units' unless defined($title) and $title ne '';
	my $analytics = -r 'analytics.txt' ?  `cat analytics.txt` : '';
	# my $analytics = ''; # disabled for now
	$HTML = HTML::Template->new(utf8 => 1, filename => $HTMLtemplateFile);
	print "Content-Type: text/html; charset=utf-8\n\n";
} # init

sub doWork {
	my $text = param('text');
	if (defined($text)) {
		open LOG, ">>log";
		print LOG "text: $text\n";
		close LOG;
		$HTML->param(query => 1);
		# $HTML->param(text => $text);
		readEvalPrint($text);
		$HTML->param(result => join('', @resultHTML));
	} else { 
		open LOG, ">>log";
		print LOG "no text\n";
		close LOG;
		my @constantsHTML;
		for my $key (sort keys %constants) {
			push @constantsHTML, {entry =>
				"$key: " .  valToString($constants{$key}) .
				" ($cNames{$key})"};
		}
		$HTML->param(constants => \@constantsHTML);
	}
} # doWork

sub finalize {
	print $HTML->output();
} # finalize

# arithmetic

sub toPower {
	my ($dimVal, $power) = @_;
	if (int($power) != $power) {
		return (valError("non-integer power"));
	}
	my $base = ${$dimVal}[0];
	my $value = 1;
	my $count = $power;
	while ($count) {
		if ($count > 0) {
			$value *= $base;
			$count -= 1;
		} else {
			$value /= $base;
			$count += 1;
		}
	} # while count
	my $answer = [$value];
	for my $index (1 .. $#{$dimVal}) {
		push @$answer, ${$dimVal}[$index] * $power;
	}
	return $answer;
} # toPower

sub copyVal { # shallow copy
	my ($val) = @_;
	my $answer = [];
	for my $component (@$val) {
		push @$answer, $component;
	}
	return $answer;
} # copyVal

sub valError {
	my ($msg) = @_;
	my $answer = copyVal($bad);
	${$answer}[1] = $msg;
	return($answer);
} # valError

sub parseError {
	my ($query, $msg) = @_;
	my $answer = copyVal($bad);
	${$answer}[1] = $msg;
	# print "Parse error: $msg; remaining query is $query\n";
	return($query, $answer);
} # parseError

sub doOp {
	my ($first, $second, $operator) = @_;
	my $answer;
	my ($val1, $val2) = (${$first}[0], ${$second}[0]);
	if ($val1 eq 'NaN' and $val2 eq 'NaN') { # two errors; compound them
		return(valError("${$first}[1], ${$second}[1]"));
	}
	return $first if ($val1 eq 'NaN');
	return $second if ($val2 eq 'NaN');
	if ($operator =~ /[+\-]/) { # addition/subtraction
		if (!isSameDim($first, $second)) {
			return (valError "dimension error");
		}
		$answer = $operator eq '+'
			? [$val1 + $val2] : [$val1 - $val2];
		for my $index (1 .. $#{$first}) {
			push @$answer, ${$first}[$index];
		}
	} elsif ($operator =~ /[\*\/]/) { # multiplication/division
		if ($operator eq '/' and $val2 eq 0) {
			return (valError "division by 0");
		}
		$answer = $operator eq '*'
			? [$val1 * $val2] : [$val1 / $val2];
		for my $index (1 .. $#{$first}) {
			push @$answer, $operator eq '*'
				? ${$first}[$index] + ${$second}[$index]
				: ${$first}[$index] - ${$second}[$index];
		}
	} else {
		return (valError "Unknown operator $operator");
	}
	return $answer;
} # doOp

# lexical analyzer
sub match {
	my ($query, $token) = @_;
	if ($query =~ s/^\s*\Q$token\E//s) {
		return($query);
	} else {
		warn("expected $token but did not find it\n");
		return($query);
	}
} # match

# all parsing routines take a query, return (remainder, expansion)

sub isSameDim {
	my ($a, $b) = @_;
	for my $index (1 .. $#{$a}) {
		return 0 if (${$a}[$index] != ${$b}[$index]);
	}
	return 1;
} # isSameDim

sub isScalar {
	my ($dimVal) = @_;
	for my $index (1 .. $#{$dimVal}) {
		return 0 if (${$dimVal}[$index]);
	}
	return 1;
} # isSameDim

sub valToString {
	my ($dimVal) = @_;
	my @pos = ();
	my @neg = ();
	my $exponent;
	my $val = ${$dimVal}[0];
	# adjust g to kg for printing purposes
	return '' unless defined($val); # currencies start undefined
	my $gramExponent = $val eq 'NaN' ? 0 : ${$dimVal}[1];
	# print "gramExponent is $gramExponent\n";
	while ($gramExponent) {
		if ($gramExponent > 0) {
			$val /= 1000.0;
			$gramExponent -= 1;
		} else {
			$val *= 1000;
			$gramExponent += 1;
		}
	} # while count
	return ("invalid: ${$dimVal}[1]") if $val eq 'NaN';
	for my $index (1 .. $#{$dimVal}) {
		$exponent = ${$dimVal}[$index];
		if ($exponent > 0) {
			push @pos, $names[$index] .
				($exponent == 1 ? '' : "^$exponent");
		} elsif ($exponent < 0) {
			$exponent = -$exponent;
			push @neg, $names[$index] .
				($exponent == 1 ? '' : "^$exponent");
		}
	}
	$val .= ' ' if @pos;
	if (@neg > 1) {
		return "$val" . join(' ', @pos) . '/(' . join(' ', @neg) .
			')';
	} elsif (@neg == 1) {
		return "$val" . join(' ', @pos) . '/' . join(' ', @neg);
	} elsif (!@neg) {
		return "$val" . join(' ', @pos);
	} else {
		return "I can't handle this value: " . Dumper($dimVal);
	}
} # valToString 

sub printVal {
	my ($msg, $val) = @_;
	if (defined(${$val}[0])) {
		push @resultHTML, $msg . valToString($val);
	} else { # an undefined initial value
		push @resultHTML, $msg;
	}
} # printVal

# recursive-descent parser. 

=cut
	expr -> terms [(+|-) expr]
	terms -> primary [(*|/|λ) terms]
	primary -> - primary
	primary -> ( expr )
	primary -> NUM | ID
=cut

sub expr { # the main routine
	my ($query) = @_;
	my (@first, @rest);
	# print "expr: $query\n";
	my $first;
	($query, $first) = terms($query);
	# printVal "first: ", $first;
	if ($query =~ s/^\s*([+\-])//) { # an operator
		my $operator = $1;
		my $second;
		($query, $second) = expr($query);
		return ($query, doOp($first, $second, $operator));
	} else { # no operator
		return ($query, $first);
	} # no operator
} # expr

sub terms {
	my ($query) = @_;
	my (@first, @rest);
	# print "terms: $query\n";
	my $first;
	($query, $first) = primary($query);
	if ($query =~ s/^\s*([*\/\w\(])//) { 
		my $operator = $1;
		if ($operator =~ /[\w\(]/) { # implicit multiplication
			$query = "$operator$query"; # replace stolen character
			$operator = '*';
			# print "implicit multiplication\n";
		}
		my $second;
		($query, $second) = terms($query);
		# printVal "Second is ", $second;
		return ($query, doOp($first, $second, $operator));
	} else {
		return ($query, $first);
	}
} # terms

sub primary {
	my ($query) = @_;
	# print "primary: $query\n";
	my ($contents, $answer);
	my $token;
	if ($query =~ s/^\s*-//) { # negation
		($query, $contents) = primary($query);
		$answer = copyVal($contents);
		${$answer}[0] = -${$answer}[0];
		return($query, $answer);
	}
	if ($query =~ s/^\s*\(//) {
		($query, $contents) = expr($query);
		$query = match($query, ')');
		# printVal "parenthesized expression; returning ", $contents;
		$answer = $contents;
	} elsif ($query =~ s/^\s*([\d\.]+)//) { # number
		$token = $1;
		if ($token =~ /\..*\./) { # multiple decimal points
			push @resultHTML, "$token is invalid; assuming zero.\n";
			return ($query, $zero);
		}
		$answer = copyVal($zero);
		${$answer}[0] = $token;
		# printVal "returning number: ", $answer;
	} elsif ($query =~ s/^\s*(\w+)//) { # id
		$token = $1;
		# try looking up the id
		$answer = $variables{$token};
		if (!defined($answer)) { # not a variable; try a constant
			$answer = $constants{$token};
			if (defined($answer) and !defined(${$answer}[0])) {
				# a currency, with undefined value.
				${$constants{$token}}[0] = getCurrency($token);
				$answer = $constants{$token};
			}
		}
		if (!defined($answer)) { # not a constant, try multiplier
			if ($token =~ /^(.)(\w+)$/ && defined($multipliers{$1})
					&& defined($constants{$2})) {
				my ($multiplier, $unit) = ($1, $2);
				$answer = copyVal($constants{$unit});
				${$answer}[0] *= $multipliers{$multiplier};
			} # will work
		} # try a multiplier prefix
	}
	if (defined($answer)) {
		# printVal "got id: ", $answer;
		if ($query =~ s/^\s*\^//) { # exponent
			my ($rest, $exponent) = primary($query);
			if (isScalar($exponent)) {
				return ($rest, toPower($answer, ${$exponent}[0]));
			} else {
				return parseError($rest, "exponent is not scalar");
			}
		} else { # no exponent
			return ($query, $answer);
		}
	} elsif (defined($token)) {
		return parseError($query, "\"$token\" is not defined");
	} else {
		return parseError($query, "missing token");
	}
} # primary

# a wrapper around expr()
sub parseExpr {
	my ($string) = @_;
	return ('') if ($string =~ /^\s*$/); # trivial case
	my ($extra, $results) = expr($string);
	# printVal "parseExpr: result will be ", $results;
	if ($extra =~ /\S/) {
		return valError("$string is malformed before '$extra'");
	}
	return $results;
} # parseExpr

# returns a float: how many USD a $valuta is worth
sub getCurrency { # this code is modified from Seifalla Moustafa's code
	my ($valuta) = @_; # such as GBP or IDR
	my $data; # all currencies
	my @stats = stat $currencyFile;
	my $mtime = $stats[9];
	if (!defined($mtime) or (time - $mtime > 24*3600)) { # old or missing
		if (!defined ($connector)) { # first time we need a currency
			# print STDERR "using connector\n";
			$connector = LWP::UserAgent->new();
			my @codes  = ();
			$codes[0] = 'USD'; # our standard
			my $a = 0;
			my $conn_cache = LWP::ConnCache->new;
			$conn_cache->total_capacity([1]);
			$connector->conn_cache($conn_cache);
			my $conn_cache = LWP::ConnCache->new; # for a persistant connection
			$conn_cache->total_capacity([1]);
			$connector->conn_cache($conn_cache);
		} # first time
		my $url = "https://v6.exchangerate-api.com/v6/$privateKey/latest/USD";
		# print "URL: $url\n";
		my $response = $connector->get($url);
		# print "Debug: " . $response->content . "\n";
		$data = $response->content;
		open DATA, ">$currencyFile";
		print DATA $data;
		close DATA;
	} else {
		open DATA, "$currencyFile";
		$/ = undef;
		$data = <DATA>;
		close DATA;
	}
	$data =~ /"$valuta":([\d\.]+)/; 
	my $answer = 1.0/$1;
	# print STDERR "answer is $answer\n";
	return ($answer);
} # getCurrency

sub addSIUnits { # Système international d'unités
	$constants{'cc'} = parseExpr('cm^3');
		$cNames{'cc'} = 'cubic centimeter';
		push @{$standardUnits{'volume'}}, 'cc';
	$constants{'l'} = parseExpr('1000 cc'); # liter
		$cNames{'l'} = 'liter';
		push @{$standardUnits{'volume'}}, 'l';
	$constants{'hectare'} = parseExpr('(100 m)^2'); # hectare
		$cNames{'hectare'} = 'hectare';
		push @{$standardUnits{'area'}}, 'hectare';
	$constants{'dunam'} = parseExpr('1000 m^2'); # dunam (Ottoman)
		$cNames{'dunam'} = 'dunam';
		push @{$standardUnits{'area'}}, 'dunam';
	$constants{'Hz'} = parseExpr('1/s'); # Hertz (frequency)
		$cNames{'Hz'} = 'Hertz';
	$constants{'Å'} = parseExpr('m / 10^10'); # Angstrom 
		$cNames{'Å'} = 'Angstrom';
		push @{$standardUnits{'distance'}}, 'Å';
	$constants{'N'} = parseExpr('kg * m / s^2'); # Newton
		$cNames{'N'} = 'Newton';
		push @{$standardUnits{'force'}}, 'N';
	$constants{'J'} = parseExpr('N * m'); # joule
		$cNames{'J'} = 'Joule';
		push @{$standardUnits{'energy'}}, 'J';
	$constants{'W'} = parseExpr('J / s'); # watt
		$cNames{'W'} = 'Watt';
		push @{$standardUnits{'power'}}, 'W';
	$constants{'Pa'} = parseExpr('N / m^2'); # pascal
		$cNames{'Pa'} = 'Pascal';
		push @{$standardUnits{'pressure'}}, 'Pa';
	$constants{'C'} = parseExpr('s * A'); # coulomb
		$cNames{'C'} = 'Coulomb';
		push @{$standardUnits{'electromagnetic'}}, 'C';
	$constants{'V'} = parseExpr('W / A'); # volt
		$cNames{'V'} = 'Volt';
		push @{$standardUnits{'electromagnetic'}}, 'V';
	$constants{'F'} = parseExpr('C / V'); # farad (capacitance)
		$cNames{'F'} = 'Farad';
		push @{$standardUnits{'electromagnetic'}}, 'F';
	$constants{'Ω'} = parseExpr('V / A'); # ohm (resistance)
		$cNames{'Ω'} = 'Ohm';
		push @{$standardUnits{'electromagnetic'}}, 'Ω';
	$constants{'S'} = parseExpr('A / V'); # siemens (conductance)
		$cNames{'S'} = 'Siemens';
		push @{$standardUnits{'electromagnetic'}}, 'S';
	$constants{'Wb'} = parseExpr('V * s'); # weber (magnetic flux)
		$cNames{'Wb'} = 'weber';
		push @{$standardUnits{'electromagnetic'}}, 'Wb';
	$constants{'Mx'} = parseExpr('Wb / 10^8'); # maxwell (magnetic flux)
		$cNames{'Mx'} = 'maxwell';
		push @{$standardUnits{'electromagnetic'}}, 'Mx';
	$constants{'Ts'} = parseExpr('Wb / m^2'); # tesla (flux density)
		$cNames{'Ts'} = 'Tesla';
		push @{$standardUnits{'electromagnetic'}}, 'Ts';
	$constants{'H'} = parseExpr('Wb / A'); # henry (inductance)
		$cNames{'H'} = 'Henry';
		push @{$standardUnits{'electromagnetic'}}, 'H';
	$constants{'Gy'} = parseExpr('J / kg'); # gray (absorbed dose)
		$cNames{'Gy'} = 'Gray';
		push @{$standardUnits{'radiation'}}, 'Gy';
	$constants{'rad'} = parseExpr('Gy / 100');
		$cNames{'rad'} = 'rad';
		push @{$standardUnits{'radiation'}}, 'rad';
	$constants{'Sv'} = parseExpr('J / kg'); # sievert (equiv dose)
		$cNames{'Sv'} = 'Sievert';
		push @{$standardUnits{'radiation'}}, 'Sv';
	$constants{'Bq'} = parseExpr('1 / s'); # becquerel (disintegations/sec)
		$cNames{'Bq'} = 'becquerel';
		push @{$standardUnits{'radiation'}}, 'Bq';
	$constants{'Ci'} = parseExpr('3.7 10^10 Bq');
		$cNames{'Ci'} = 'curie';
		push @{$standardUnits{'radiation'}}, 'Ci';
	$constants{'rd'} = parseExpr('MBq');
		$cNames{'rd'} = 'rutherford';
		push @{$standardUnits{'radiation'}}, 'rd';
	$constants{'kat'} = parseExpr('mol / s'); # katal (catalytic act)
		$cNames{'kat'} = 'katal';
	$constants{'Rvalue'} = parseExpr('m^2 K / W'); # insulation
		$cNames{'Rvalue'} = 'R value';
	$constants{'molal'} = parseExpr('mol / kg');
		$cNames{'molal'} = 'molal';
	$constants{'pc'} = parseExpr('3.08567758149137 * 10^16 m');
		$cNames{'pc'} = 'parsec';
		push @{$standardUnits{'distance'}}, 'pc';
} # addSIUnits

sub addPhysicsConstants { # measured quantities
	$constants{'c'} = parseExpr('299792458m/s'); # speed of light
		$cNames{'c'} = 'speed of light';
		push @{$standardUnits{'velocity'}}, 'c';
	$constants{'L'} = parseExpr('6.02214076 10^23 / mol');
		$cNames{'L'} = 'Avogadro\'s number';
		# Avogadro's number
	$constants{'F'} = parseExpr('96485.3365 C/mol'); 
		$cNames{'F'} = 'Faraday constant';
		# Faraday constant
	$constants{'e'} = parseExpr('1.602176634 * 10^(-19) A s'); # charge on an electron
		$cNames{'e'} = 'electron charge';
		push @{$standardUnits{'electromagnetic'}}, 'e';
	$constants{'k_e'} = parseExpr('8.987551 10^9 N m^2 / C^2'); 
		$cNames{'k_e'} = 'Coulomb constant';
		# Coulomb constant
	$constants{'G'} = parseExpr('(6.67384/10^11) m^3 / (kg s^2) '); 
		$cNames{'G'} = 'gravitational constant';
		# Gravitational constant
	$constants{'R'} = parseExpr('8.314 (J/K mol)'); # gas constant
		$cNames{'R'} = 'gas constant';
	$constants{'h'} = parseExpr('6.62607015 10^-34 J s'); # Planck constant
		$cNames{'h'} = 'Planck constant';
	$constants{'π'} = parseExpr('3.1415926535');
		$cNames{'π'} = 'pi';
	$constants{'ℏ'} = parseExpr('h/(2 * π)'); # Dirac constant
		$cNames{'ℏ'} = 'Dirac constant';
	$constants{'atm'} = parseExpr('101325 Pa');
		$cNames{'atm'} = 'atmosphere';
		push @{$standardUnits{'pressure'}}, 'atm';
	$constants{'Torr'} = parseExpr('atm / 760'); # named after Torricelli
		$cNames{'Torr'} = 'torr';
		push @{$standardUnits{'pressure'}}, 'Torr';
	$constants{'mmHg'} = parseExpr('133.322387415 Pa');
		$cNames{'mmHg'} = 'mm of mercury';
		push @{$standardUnits{'pressure'}}, 'mmHg';
	$constants{'bar'} = parseExpr('100 kPa');
		$cNames{'bar'} = 'bar';
		push @{$standardUnits{'pressure'}}, 'bar';
	$constants{'k'} = parseExpr('1.380649 * 10^(-23) J / K');
		$cNames{'k'} = 'Boltzmann constant';
	$constants{'eV'} = parseExpr('1.602176634 * 10^(-19) J');
		$cNames{'eV'} = 'electron volt';
		push @{$standardUnits{'energy'}}, 'eV';
} # addPhysicsConstants

sub addEnglishUnits {
	# http://en.wikipedia.org/wiki/United_States_customary_units
	# distance
	$constants{'ft'} = parseExpr('0.3048 m'); # international foot
		$cNames{'ft'} = 'foot';
		push @{$standardUnits{'distance'}}, 'ft';
	$constants{'yd'} = parseExpr('3 ft'); # yard
		$cNames{'yd'} = 'yard';
		push @{$standardUnits{'distance'}}, 'yd';
	$constants{'ftm'} = parseExpr('2 yd'); # fathom
		$cNames{'ftm'} = 'fathom';
		push @{$standardUnits{'distance'}}, 'ftm';
	$constants{'cb'} = parseExpr('120 ftm'); # cable
		$cNames{'cb'} = 'cable';
		push @{$standardUnits{'distance'}}, 'cb';
	$constants{'rod'} = parseExpr('16.5 ft'); # rod
		$cNames{'rod'} = 'rod';
		push @{$standardUnits{'distance'}}, 'rod';
	$constants{'ch'} = parseExpr('4 rod'); # chain
		$cNames{'ch'} = 'chain';
		push @{$standardUnits{'distance'}}, 'ch';
	$constants{'fur'} = parseExpr('10 ch'); # furlong
		$cNames{'fur'} = 'furlong';
		push @{$standardUnits{'distance'}}, 'fur';
	$constants{'in'} = parseExpr('ft/12');
		$cNames{'in'} = 'inch';
		push @{$standardUnits{'distance'}}, 'in';
	$constants{'mi'} = parseExpr('5280 ft'); # mile
		$cNames{'mi'} = 'mile';
		push @{$standardUnits{'distance'}}, 'mi';
	$constants{'nmi'} = parseExpr('1.151 mi'); # nautical mile
		$cNames{'nmi'} = 'nautical mile';
		push @{$standardUnits{'distance'}}, 'nmi';
	$constants{'lea'} = parseExpr('3 mi'); # league
		$cNames{'lea'} = 'league';
		push @{$standardUnits{'distance'}}, 'lea';
	# area
	$constants{'acre'} = parseExpr('mi^2 / 640 ');
		$cNames{'acre'} = 'acre';
		push @{$standardUnits{'area'}}, 'acre';
	$constants{'twp'} = parseExpr('4 lea^2'); # survey township
		$cNames{'twp'} = 'township';
		push @{$standardUnits{'area'}}, 'twp';
	# volume (liquid)
	$constants{'minim'} = parseExpr('61.611519922 μl'); # minim
		$cNames{'minim'} = 'minim';
	$constants{'fldr'} = parseExpr('60 minim'); # fluid dram
		$cNames{'fldr'} = 'fluid dram';
	$constants{'tsp'} = parseExpr('80 minim'); # teaspoon
		$cNames{'tsp'} = 'teaspoon';
		push @{$standardUnits{'volume'}}, 'tsp';
	$constants{'Tbsp'} = parseExpr('3 tsp'); # teaspoon
		$cNames{'Tbsp'} = 'tablespoon';
		push @{$standardUnits{'volume'}}, 'Tbsp';
	$constants{'floz'} = parseExpr('2 Tbsp'); # fluid ounce
		$cNames{'floz'} = 'fluid ounce';
		push @{$standardUnits{'volume'}}, 'floz';
	$constants{'jig'} = parseExpr('3 Tbsp'); # jigger
		$cNames{'jig'} = 'jigger';
		push @{$standardUnits{'volume'}}, 'jig';
	$constants{'gi'} = parseExpr('4 floz'); # US gill
		$cNames{'gi'} = 'US gill';
		push @{$standardUnits{'volume'}}, 'gi';
	$constants{'cp'} = parseExpr('2 gi'); # US cup
		$cNames{'cp'} = 'US cup';
		push @{$standardUnits{'volume'}}, 'cp';
	$constants{'pt'} = parseExpr('2 cp'); # US pint
		$cNames{'pt'} = 'US pint';
		push @{$standardUnits{'volume'}}, 'pt';
	$constants{'qt'} = parseExpr('2 pt'); # US quart
		$cNames{'qt'} = 'US quart';
		push @{$standardUnits{'volume'}}, 'qt';
	$constants{'gal'} = parseExpr('4 qt'); # US gallon
		$cNames{'gal'} = 'US gallon';
		push @{$standardUnits{'volume'}}, 'gal';
	$constants{'uk_gal'} = parseExpr('4.54609 l'); # Imperial (UK) gallon
		$cNames{'uk_gal'} = 'UK gallon';
		push @{$standardUnits{'volume'}}, 'uk_gal';
	$constants{'bbl'} = parseExpr('31.5 gal'); # barrel
		$cNames{'bbl'} = 'barrel';
		push @{$standardUnits{'volume'}}, 'bbl';
	$constants{'hogshead'} = parseExpr('63 gal'); 
		$cNames{'hogshead'} = 'hogshead';
		push @{$standardUnits{'volume'}}, 'hogshead';
	# volume (solid)
	$constants{'dry_pt'} = parseExpr('0.5506105 l'); 
		$cNames{'dry_pt'} = 'dry pint';
	$constants{'dry_qt'} = parseExpr('2 dry_pt'); 
		$cNames{'dry_qt'} = 'dry quart';
	$constants{'dry_gal'} = parseExpr('4 dry_qt'); 
		$cNames{'dry_gal'} = 'dry gallon';
	$constants{'peck'} = parseExpr('2 dry_gal'); 
		$cNames{'peck'} = 'peck';
	$constants{'bu'} = parseExpr('4 peck'); # bushel
		$cNames{'bu'} = 'bushel';
	$constants{'dry_bbl'} = parseExpr('3.281 bu'); # dry barrel
		$cNames{'dry_bbl'} = 'dry barrel';
	# time
	$constants{'min'} = parseExpr('60 s');
		$cNames{'min'} = 'minute';
		push @{$standardUnits{'time'}}, 'min';
	$constants{'hr'} = parseExpr('60 min');
		$cNames{'hr'} = 'hour';
		push @{$standardUnits{'time'}}, 'hr';
	$constants{'day'} = parseExpr('24 hr');
		$cNames{'day'} = 'day';
		push @{$standardUnits{'time'}}, 'day';
	# mass (Avoirdupois, not Troy)
	$constants{'lb'} = parseExpr('453.592 g'); # pounds of mass
		$cNames{'lb'} = 'pounds of mass';
		push @{$standardUnits{'mass'}}, 'lb';
	$constants{'gr'} = parseExpr('lb/7000'); # grain
		$cNames{'gr'} = 'grain';
	$constants{'dr'} = parseExpr('(27 + 11/32) gr'); # dram 
		$cNames{'dr'} = 'dram';
	$constants{'oz'} = parseExpr('16 dr'); # ounce 
		$cNames{'oz'} = 'ounce';
		push @{$standardUnits{'mass'}}, 'oz';
	$constants{'cwt'} = parseExpr('100 lb'); # US hundredweight 
		$cNames{'cwt'} = 'US hundredweight';
	$constants{'ton'} = parseExpr('20 cwt'); # US ton (short ton) 
		$cNames{'ton'} = 'US ton (short ton)';
		push @{$standardUnits{'mass'}}, 'ton';
	$constants{'stone'} = parseExpr('14 lb'); # British/Irish stone (not Chinese)
		$cNames{'stone'} = 'British/Irish stone';
		push @{$standardUnits{'mass'}}, 'stone';
	# force
	$constants{'lbF'} = parseExpr('4.44822 N'); # pounds of force
		$cNames{'lbF'} = 'pounds of force';
		push @{$standardUnits{'force'}}, 'lbF';
	$constants{'slug'} = parseExpr('lbF s^2/ft'); # mass, Imperial
		$cNames{'slug'} = 'slug';
	# temperature
	$constants{'degF'} = parseExpr('5 K / 9'); # Δ degrees Fahrenheit
		$cNames{'degF'} = 'Δ degrees Fahrenheit';
	# energy
	$constants{'Btu'} = parseExpr('1055.05585 J'); # British thermal
		$cNames{'Btu'} = 'British thermal unit';
		push @{$standardUnits{'energy'}}, 'Btu';
	$constants{'cal'} = parseExpr('4.184090 J'); # calories
		$cNames{'cal'} = 'calorie';
		push @{$standardUnits{'energy'}}, 'cal';
	# power
	$constants{'hp'} = parseExpr('745.699872 W'); # horsepower
		$cNames{'hp'} = 'horsepower (mechanical)';
		push @{$standardUnits{'power'}}, 'hp';
	# insulation
	$constants{'Rvalue_US'} = parseExpr('ft^2 degF hr /Btu'); 
		$cNames{'Rvalue_US'} = 'US R value';
} # addEnglishUnits

sub addRussianUnits {
	# http://en.wikipedia.org/wiki/Obsolete_Russian_weights_and_measures
	# mass
	$constants{'funt'} = parseExpr('409.51718 g'); # фунт
		$cNames{'funt'} = 'фунт';
	$constants{'dolia'} = parseExpr('funt * 1/9216'); # до́ля 
		$cNames{'dolia'} = 'до́ля';
	$constants{'zolotnik'} = parseExpr('funt * 1/96'); # золотни́к 
		$cNames{'zolotnik'} = 'золотни́к';
	$constants{'lot'} = parseExpr('funt * 1/32'); # лот 
		$cNames{'lot'} = 'лот';
	$constants{'pood'} = parseExpr('funt * 40'); # пуд 
		$cNames{'pood'} = 'пуд';
	$constants{'berkovets'} = parseExpr('funt * 400'); # берковец 
		$cNames{'berkovets'} = 'берковец';
	# distance 
	$constants{'tochka'} = parseExpr('in / 100'); # то́чка
		$cNames{'tochka'} = 'то́чка';
	$constants{'liniya'} = parseExpr('in / 10'); # ли́ния
		$cNames{'liniya'} = 'ли́ния';
	$constants{'duiym'} = parseExpr('in'); # дюйм
		$cNames{'duiym'} = 'дюйм';
	$constants{'vershok'} = parseExpr('1.75 in'); # вершо́к
		$cNames{'vershok'} = 'вершо́к';
	$constants{'piad'} = parseExpr('7 in'); # пядь
		$cNames{'piad'} = 'пядь';
	$constants{'fut'} = parseExpr('ft'); # фут
		$cNames{'fut'} = 'фут';
	$constants{'arshin'} = parseExpr('7 ft / 3'); # арши́н
		$cNames{'arshin'} = 'арши́н';
	$constants{'sazhen'} = parseExpr('7 ft'); # са́жень
		$cNames{'sazhen'} = 'са́жень';
	$constants{'versta'} = parseExpr('3500 ft'); # верста́
		$cNames{'versta'} = 'верста́';
	$constants{'milia'} = parseExpr('24500 ft'); # ми́ля
		$cNames{'milia'} = 'ми́ля';
	# area
	$constants{'desiatina'} = parseExpr('2400 sazhen^2'); # десяти́на (treasury/official)
		$cNames{'desiatina'} = 'десяти́на';
		# proprietor's desiatina is 3200 sazhen^2
	# volume (solid)
	$constants{'garnets'} = parseExpr('3.279842 l'); # га́рнец
		$cNames{'garnets'} = 'га́рнец';
	$constants{'chast'} = parseExpr('garnets * 1/30'); # часть     
		$cNames{'chast'} = 'часть';
	$constants{'kruzhka'} = parseExpr('garnets * 2/5'); #  кру́жка    
		$cNames{'kruzhka'} = 'кру́жка';
	$constants{'vedro'} = parseExpr('garnets * 4'); #    ведро́     
		$cNames{'vedro'} = 'ведро́';
	$constants{'chetverik'} = parseExpr('garnets * 8'); #    четвери́к  
		$cNames{'chetverik'} = 'четвери́к';
	$constants{'osmina'} = parseExpr('garnets * 32'); #   осьми́на   
		$cNames{'osmina'} = 'осьми́на';
	$constants{'chetvert'} = parseExpr('garnets * 64'); #   че́тверть  
		$cNames{'chetvert'} = 'че́тверть';
	# volume (liquid)
	$constants{'vedro'} = parseExpr('12.29941 l'); # ведро́
		$cNames{'vedro'} = 'ведро́';
	$constants{'shkalik'} = parseExpr('vedro * 1/200'); # шка́лик 
		$cNames{'shkalik'} = 'шка́лик';
	$constants{'charka'} = parseExpr('vedro * 1/100'); # ча́рка 
		$cNames{'charka'} = 'ча́рка';
	$constants{'butylka_vodochnaya'} = parseExpr('vedro * 1/20'); # буты́лка_во́дочная
		$cNames{'butylka_vodochnaya'} = 'буты́лка_во́дочная';
	$constants{'butylka_vinnaya'} = parseExpr('vedro * 1/16'); # буты́лка_ви́нная 
		$cNames{'butylka_vinnaya'} = 'буты́лка_ви́нная';
	$constants{'kruzhka'} = parseExpr('vedro * 1/10'); # кру́жка 
		$cNames{'kruzhka'} = 'кру́жка';
	$constants{'shtof'} = parseExpr('vedro * 1/10'); # штоф 
		$cNames{'shtof'} = 'штоф';
	$constants{'bochka'} = parseExpr('vedro * 40'); # бо́чка 
		$cNames{'bochka'} = 'бо́чка';
	# there are other units as well
} # addRussianUnits

sub addCurrencyUnits {
	my %currencies = (
		AED => 'United Arab Emirates Dirham',
		AMD => 'Armenian Dram',
		ANG => 'Netherlands Antillian Guilder',
		AOA => 'Angolan Kwanza',
		ARS => 'Argentine Peso',
		AUD => 'Australian Dollar',
		BBD => 'Barbados Dollar',
		BDT => 'Bangladeshi Taka',
		BGN => 'Bulgarian Lev',
		BHD => 'Bahraini Dinar',
		BRL => 'Brazilian Real',
		BSD => 'Bahamian Dollar',
		BWP => 'Botswana Pula',
		CAD => 'Canadian Dollar',
		CHF => 'Swiss Franc',
		CLP => 'Chilean Peso',
		CNY => 'Chinese Renminbi',
		COP => 'Colombian Peso',
		CZK => 'Czech Koruna',
		DKK => 'Danish Krone',
		DOP => 'Dominican Peso',
		EGP => 'Egyptian Pound',
		ETB => 'Ethiopian Birr',
		EUR => 'Euro',
		FJD => 'Fiji Dollar',
		GBP => 'United Kingdom Pound Sterling',
		GHS => 'Ghanaian Cedi',
		GTQ => 'Guatemalan Quetzal',
		HKD => 'Hong Kong Dollar',
		HNL => 'Honduran Lempira',
		HRK => 'Croatian Kuna',
		HUF => 'Hungarian Forint',
		IDR => 'Indonesian Rupiah',
		ILS => 'Israeli Shekel',
		INR => 'Indian Rupee',
		IQD => 'Iraqi Dinar',
		IRR => 'Iranian Rial',
		ISK => 'Icelandic Krona',
		JMD => 'Jamaican Dollar',
		JOD => 'Jordanian Dinar',
		JPY => 'Japanese Yen',
		KES => 'Kenyan Shilling',
		KHR => 'Cambodian Riel',
		KRW => 'Korean Won',
		KWD => 'Kuwaiti Dinar',
		KZT => 'Kazakhstani Tenge',
		LAK => 'Lao Kip',
		LKR => 'Sri Lanka Rupee',
		MAD => 'Moroccan Dirham',
		MKD => 'Macedonian Denar',
		MMK => 'Myanmar Kyat',
		MUR => 'Mauritian Rupee',
		MXN => 'Mexican Peso',
		MYR => 'Malaysian Ringgit',
		NAD => 'Namibian Dollar',
		NGN => 'Nigerian Naira',
		NOK => 'Norwegian Krone',
		NZD => 'New Zealand Dollar',
		OMR => 'Omani Rial',
		PAB => 'Panamanian Balboa',
		PEN => 'Peruvian Nuevo Sol',
		PGK => 'Papua New Guinean Kina',
		PHP => 'Philippine Peso',
		PKR => 'Pakistani Rupee',
		PLN => 'Polish Zloty',
		PYG => 'Paraguayan Guarani',
		QAR => 'Qatari Riyal',
		RON => 'Romanian Leu',
		RSD => 'Serbian Dinar',
		RUB => 'Russian Rouble',
		SAR => 'Saudi Riyal',
		SCR => 'Seychellois Rupee',
		SEK => 'Swedish Krona',
		SGD => 'Singapore Dollar',
		THB => 'Thai Baht',
		TJS => 'Tajikistani Somoni',
		TND => 'Tunisian Dinar',
		TRY => 'Turkish Lira',
		TTD => 'Trinidad And Tobago Dollar',
		TWD => 'New Taiwan Dollar',
		TZS => 'Tanzanian Shilling',
		UAH => 'Ukrainian Hryvnia',
		USD => 'United States Dollar',
		UYU => 'Uruguayan Peso',
		UZS => 'Uzbekistani Som',
		VEF => 'Venezuelan Bolivar Fuerte',
		VND => 'Vietnamese Dong',
		XAF => 'CFA Franc Central',
		XCD => 'East Caribbean Dollar',
		XOF => 'CFA Franc West',
		XPF => 'French Pacific Francs',
		ZAR => 'South African Rand',
		ZMW => 'Zambian Kwacha',
	);
	for my $key (keys %currencies) {
		$constants{$key} = parseExpr('USD * 1'); # it's currency
		${$constants{$key}}[0] = undef;  # with an undefined value
		$cNames{$key} = $currencies{$key};
		push @{$standardUnits{'currency'}}, $key;
	}
} # addCurrencyUnits

sub complexUnits {
	push @{$standardUnits{'velocity'}}, "mi/hr";
		$cNames{"mi/hr"} = "miles / hour";
	push @{$standardUnits{'velocity'}}, "km/hr";
		$cNames{"km/hr"} = "kilometers / hour";
} # complexUnits

# generate data for HTML template
sub outputUnits {
	my @HTMLUnits;
	for my $dimension (sort keys %standardUnits) {
		# next if ($dimension =~ /HASH/); # why does this happen?
		my @details;
		for my $unit (sort {
					# lc($cNames{$a}) cmp lc($cNames{$b})
					if (defined(${$constants{$a}}[0])) {
						${$constants{$a}}[0] <=> ${$constants{$b}}[0]
					} else { # most likely currency
						lc($cNames{$a}) cmp lc($cNames{$b})
					}
				} @{$standardUnits{$dimension}}) {
			# print "unit $unit, longName $cNames{$unit}\n";
			push @details, {unit => $unit, longName => $cNames{$unit}};
		}
		push @HTMLUnits, {
			dimension => $dimension,
			entry => \@details,
		};
	} # each dimension
	$HTML->param(dimensions => \@HTMLUnits);
} # outputUnits

sub valToDim {
	my ($dimVal) = @_;
	my @pos = ();
	my @neg = ();
	my $exponent;
	for my $index (1 .. $#{$dimVal}) {
		$exponent = ${$dimVal}[$index];
		if ($exponent > 0) {
			push @pos, $dims[$index] .
				($exponent == 1 ? '' : "^$exponent");
		} elsif ($exponent < 0) {
			$exponent = -$exponent;
			push @neg, $dims[$index] .
				($exponent == 1 ? '' : "^$exponent");
		}
	}
	if (@neg > 1) {
		return join(' ', @pos) . '/(' . join(' ', @neg) .  ')';
	} elsif (@neg == 1) {
		return join(' ', @pos) . '/' . join(' ', @neg);
	} elsif (!@neg) {
		return join(' ', @pos);
	} else {
		return "I can't handle this dimension: " . Dumper($dimVal);
	}
} # valToDim 

# given a value, returns a string showing its dimension
sub toDim {
	my ($value) = @_;
	my @dims = ('mass', 'length', 'time', 'current', 'luminosity', 'mole', "temperature", 'currency');
# initialize the array counter to 0
	my $dimCount = 0;
	my $dim = "";
	my $denominator;
	my $numerator;
	for my $index (1 .. $#{$value}){
			if(${$value}[$index] != 0){
					if(${$value}[$index] == 1) {
			if(defined($numerator)){
								$numerator = "$numerator*".$dims[$dimCount];
			}
			else{$numerator = "$numerator".$dims[$dimCount];}
					} elsif(${$value}[$index] > 1) {
			if(defined($numerator)){
								$numerator = "$numerator*".$dims[$dimCount]
								. "^" . ${$value}[$index];
			}
			else{$numerator = "$numerator".$dims[$dimCount] . "^" . ${$value}[$index];}
					}
		else {}
			}
			$dimCount = $dimCount + 1;
	}
	$dimCount = 0;
	for my $index (1 .. $#{$value}){
		if(${$value}[$index] != 0){
			if(${$value}[$index] == -1) {
				if(defined($denominator)){
					$denominator = "$denominator*".$dims[$dimCount];
				} else {$denominator = "$denominator".$dims[$dimCount];}
			}
			elsif(${$value}[$index] < -1) {
                                my $sign = -1 * ${$value}[$index];
				if(defined($denominator)){
                                	$denominator = "$denominator*".$dims[$dimCount] . "^" . $sign;
				} else {$denominator = "$denominator".$dims[$dimCount] . "^" . $sign;}
                        }
			else {}
		}
		$dimCount = $dimCount + 1;
	}
	# the denominator should be surrounded by parenthesis
	if(defined($denominator)){
		$denominator = "("."$denominator".")";
	}
	if(!defined($numerator)){
		$numerator = "1";
	}
	if(defined($denominator)){
		$dim = "($numerator)"."/"."$denominator";
	}
	else{
		$dim = $numerator;
	}
	# if the function failed to translate the input,
	# it will return an error.
	if(!defined($denominator) && $numerator == "1"){
		$dim = "invalid input";
	}
        return $dim;
} # toDim

sub readEvalPrint {
	my ($text) = @_;
	for my $line (split(/\n/, $text)) {
		chomp $line;
		$line =~ s/%.*//; # comment
		next unless $line =~ /\w/;
		$line =~ s/^\s*//; # left-justify
		$line =~ s/\s*$//; # trim
		$line =~ s/[<>]//g; # no RSS
		push @resultHTML, "<span class='input'>$line</span>\n";
		if ($line =~ /^\s*(\w+)\s*=(.*)/) { # assignment
			my ($var, $value) = ($1, $2);
			$variables{$var} = parseExpr($value);
			printVal " $var = ", $variables{$var};
		} elsif ($line =~ /^\s*convert\s+(.*)\s+to\s+(.*)/) {
			my ($orig, $new) = ($1, $2);
			$new =~ s/\s$//;
			my $result = parseExpr "(($orig) / ($new))";
			if (isScalar $result) {
				# $orig = "1 $orig" unless $orig =~ /^\d/;
				push @resultHTML, " $orig = ", valToString($result) . " $new";
			} elsif (${$result}[0] eq 'NaN') {
				printVal (" " , $result);
			} else {
				push @resultHTML, " Can't convert " .
					valToDim(parseExpr($orig)) .
					" to " .
					valToDim(parseExpr($new)) . '.';
			}
		} elsif ($line =~ /^\s*dim\s+(.*)/) {
			my $expr = $1;
			my $result = parseExpr($expr);
			push @resultHTML, ' ' . valToDim($result);
		} else { # expression
			printVal " ", parseExpr($line);
		}
		push @resultHTML, "\n";
	}
} # readEvalPrint

init();
addSIUnits();
addPhysicsConstants();
addEnglishUnits();
addRussianUnits();
addCurrencyUnits();
complexUnits();
outputUnits();
doWork();
finalize();
