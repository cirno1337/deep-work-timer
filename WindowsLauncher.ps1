Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName System.Windows.Forms

[xml]$xaml = @"
<Window
 xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
 xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
 Title="Deep Work Timer"
 Width="420"
 Height="560"
 WindowStyle="None"
 ResizeMode="NoResize"
 ShowInTaskbar="False"
 Topmost="True">

    <Grid Name="MainGrid"/>

</Window>
"@

$reader = New-Object System.Xml.XmlNodeReader $xaml
$window = [Windows.Markup.XamlReader]::Load($reader)

$grid = $window.FindName("MainGrid")

# WebView2 DLL
Add-Type -Path ".\Microsoft.Web.WebView2.Core.dll"
Add-Type -Path ".\Microsoft.Web.WebView2.Wpf.dll"

$webview = New-Object Microsoft.Web.WebView2.Wpf.WebView2
$grid.Children.Add($webview)

# Tray icon
$tray = New-Object System.Windows.Forms.NotifyIcon
$tray.Icon = [System.Drawing.SystemIcons]::Information
$tray.Text = "Deep Work Timer"
$tray.Visible = $true

$menu = New-Object System.Windows.Forms.ContextMenuStrip

$showItem = $menu.Items.Add("Show Timer")
$quitItem = $menu.Items.Add("Quit")

$showItem.add_Click({
    $window.Show()
    $window.WindowState = "Normal"
    $window.Activate()
})

$quitItem.add_Click({
    $tray.Visible = $false
    $tray.Dispose()
    $window.Close()
})

$tray.ContextMenuStrip = $menu

$tray.add_DoubleClick({
    $window.Show()
    $window.Activate()
})

# Position bottom-right
function Set-BottomRight {

    $area = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea

    $window.Left =
        $area.Width - $window.Width - 24

    $window.Top =
        $area.Height - $window.Height - 24
}

$window.Add_Loaded({

    Set-BottomRight

    $null = $webview.EnsureCoreWebView2Async()

    $webview.add_CoreWebView2InitializationCompleted({

        $file =
            Join-Path (
                Split-Path $PSCommandPath
            ) "timer.html"

        $uri = [System.Uri]::new($file)

        $webview.CoreWebView2.Settings.AreDefaultContextMenusEnabled = $false

        $webview.CoreWebView2.Navigate(
            $uri.AbsoluteUri
        )

        $webview.CoreWebView2.add_WebMessageReceived({

            param($sender,$args)

            $msg =
                $args.WebMessageAsJson |
                ConvertFrom-Json

            switch($msg.action)
            {
                "minimize" {
                    $window.Hide()
                }

                "close" {
                    $tray.Visible = $false
                    $tray.Dispose()
                    $window.Close()
                }

                "start" {
                    Write-Host "Session started"
                }

                "cancel" {
                    Write-Host "Session cancelled"
                }

                "complete" {
                    $window.Show()
                    $window.Activate()
                }
            }
        })
    })
})

$app = New-Object System.Windows.Application
$app.Run($window)