<!-- ========================================= -->
<!-- =                                       = -->
<!-- =           Discord FlexiViewer         = -->
<!-- =          RawR Copyright © 2017        = -->
<!-- =         http://raw-recruits.com       = -->
<!-- =                                       = -->
<!-- ========================================= -->

<head>
<title>Discord Viewer</title>

<!-- The style sheet where you can edit colours, font etc. -->
<link rel="stylesheet" href="css/light.css">

</head> 
<body>
<div id="bodypat">  

 <?php
header( "refresh:300;" ); 
echo "<META http-equiv='Content-Type' content='text/html; charset=UTF-8'>";

// Replace 'http://www.raw-recruits.com/discord/widget.json' with the location of your json own file, something like: 'https://discordapp.com/api/guilds/123456789987654321/widget.json'
// You'll find this in your server settings under Widget. *Be sure to turn on Enable Server Widget
$discord = json_decode(file_get_contents('http://www.raw-recruits.com/discord/widget.json'));

print "<div class=\"heading\">" . $discord->name; 

print "<br><span class=\"desc\"><img class=\"discord-icon\" src=\"images/discord_icon.png\" alt = \"icon\"/> Discord Voice Channels</span>";
print "</div>";  // Join button, replace https://discord.gg/rrnrPn4 with the link to your own server
print "<a href=\"https://discord.gg/rrnrPn4\" target=\"_blank\" class=\"div-link\"><div>Join Server</div></a><span class=\"small\"><br><br></span>";

$Admin=array();
    $fp=fopen('data/admindata.txt', 'r');
        while (!feof($fp))
            {
            $line=fgets($fp);
            $line=trim($line);
            $Admin[]=$line;
        }
    fclose($fp);
$mn = 0; // sets member number to 0
if ($discord->channels) {
    usort($discord->channels, function($a, $b) {
      return $a->position > $b->position ? 1 : -1;
    });
    foreach ($discord->members as $member) {
        if (!empty($member->channel_id)) {
            $channel_members[$member->channel_id][] = $member->username;
        }
    }
    foreach ($discord->channels as $channel) {
        if (!empty($channel_members[$channel->id])) {
             if ($mn == 0) {
                print "<div id=\"channels1st\">"; 
            } else {
                print "<div id=\"channels\">";    
              }
                print "<span class=\"channel\">&nbsp;&nbsp;".$channel->name."</span></div>";  
            print "<div id=\"content2\">"; 
                foreach($discord->{'members'} as $m) {
                    if($m->channel_id == $channel->id) {
                        print "&nbsp;&nbsp;&nbsp;&nbsp;<img class=\"discord-avatar\" src=\"".$m->avatar_url."\">";
                            If  (isset($m->nick))  { print "&nbsp;<img class=\"discord-status\" src=\"images/".$m->status.".png\">&nbsp;&nbsp;" . $m->nick; } 
                            else { print "&nbsp;<img class=\"discord-status\" src=\"images/".$m->status.".png\">&nbsp;&nbsp;" . $m->username;}
                                $mn++;  // sets member number to +1
                                    for ($for_Number = 0; $for_Number < count($Admin); $for_Number++) {
                                        if ($m->username == $Admin[$for_Number]) {
                                            Print '<span class="label-admin">ADM</span>';
                                        }   
                                    }
                                    switch ($m->self_mute) {
                                        case "true":
                                            print "&nbsp;<img class=\"mutedeaf\" src=\"images/mute_light.svg\">";
                                    }
                                    switch ($m->self_deaf) {
                                        case "true":
                                            print "&nbsp;<img class=\"mutedeaf\" src=\"images/deaf_light.svg\">";
                                    }
                                    if(isset($m->bot)) {
                                    print '<span class="label-bot">BOT</span>';
                                    }
                                    if (isset($m->game->name)) { $m->game->name = (mb_strlen($m->game->name) > 31) ? mb_substr($m->game->name, 0, 31) . '...' : $m->game->name;
                                    Print '&nbsp;<span class="label-game"><i>In</i>:&nbsp;'. ucwords(strtolower($m->game->name)) .'</span>';
                                    }
                            echo "<br>";
                    }
                }
            print "</div>";   
        }
    }
}
        
// routine for no users in server
if ($mn == "0") {
    usort($discord->channels, function($a, $b) {
      return $a->position > $b->position ? 1 : -1;
    });
    print "<div id=\"channels1st\">"; 
        foreach ($discord->channels as $channel) {
            echo "<span class=\"channel\">&nbsp;&nbsp;".$channel->name."</span><br>";
        }
    print "</div>";

    print "<div id=\"nousers\">";   
        print "<br>There are no&nbsp;";
        print "users&nbsp;<br>";
        print "on this server at<br>";
        print "the moment.<br><br>";
        print "Zzzzzzzz....<br>";
    print "</div>";  
}   else { 
       Print '<div class="location">' . $mn . ' Users</div>'; 
    }
// End of routine

$array_countall = count($discord->members);
$sum_total = $array_countall - $mn 
?>
<div class="spacer"></div>

<div class="users"> 
    
<input type="checkbox" id="toggle">
<?php echo '&nbsp;&nbsp;'; echo $array_countall - $mn; ?> More Online <label for="toggle">View</label><br><br>

<div class="hidden">

<?php
    foreach($discord->{'members'} as $m) {
        if(is_null($m->channel_id)) { 
                        print "&nbsp;&nbsp;&nbsp;&nbsp;<img class=\"discord-avatar\" src=\"".$m->avatar_url."\">";
                            If  (isset($m->nick))  { print "&nbsp;<img class=\"discord-status\" src=\"images/".$m->status.".png\">&nbsp;&nbsp;" . $m->nick; } 
                            else { print "&nbsp;<img class=\"discord-status\" src=\"images/".$m->status.".png\">&nbsp;&nbsp;" . $m->username;}
                                    for ($for_Number = 0; $for_Number < count($Admin); $for_Number++) {
                                        if ($m->username == $Admin[$for_Number]) {
                                            Print '<span class="label-admin">ADM</span>';
                                        }   
                                    }
                                    switch ($m->self_mute) {
                                        case "true":
                                            print "&nbsp;<img class=\"mutedeaf\" src=\"images/mute_light.svg\">";
                                    }
                                    switch ($m->self_deaf) {
                                        case "true":
                                            print "&nbsp;<img class=\"mutedeaf\" src=\"images/deaf_light.svg\">";
                                    }
                                    if(isset($m->bot)) {
                                    print '<span class="label-bot">BOT</span>';
                                    }
                                    if (isset($m->game->name)) { $m->game->name = (mb_strlen($m->game->name) > 31) ? mb_substr($m->game->name, 0, 31) . '...' : $m->game->name;
                                    Print '&nbsp;<span class="label-game"><i>In</i>:&nbsp;'. ucwords(strtolower($m->game->name)) .'</span>';
                                    }
                            echo "<br>";
                    }
    }
echo "<br>";
?>

</div> 

</div>


</div> 
</body>