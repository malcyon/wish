$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$code = @'
using System;
using System.Runtime.InteropServices;
namespace WishAudio {
  [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
  public class MMDeviceEnumerator {}
  [ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  public interface IMMDeviceEnumerator {
    [PreserveSig] int EnumAudioEndpoints(int flow, int stateMask, out IntPtr devices);
    [PreserveSig] int GetDefaultAudioEndpoint(int flow, int role, out IMMDevice endpoint);
  }
  [ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  public interface IMMDevice {
    [PreserveSig] int Activate(ref Guid iid, int clsctx, IntPtr activationParams, [MarshalAs(UnmanagedType.IUnknown)] out object result);
    [PreserveSig] int OpenPropertyStore(int access, out IntPtr store);
    [PreserveSig] int GetId([MarshalAs(UnmanagedType.LPWStr)] out string id);
    [PreserveSig] int GetState(out int state);
  }
  [ComImport, Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  public interface IAudioEndpointVolume {
    [PreserveSig] int RegisterControlChangeNotify(IntPtr callback);
    [PreserveSig] int UnregisterControlChangeNotify(IntPtr callback);
    [PreserveSig] int GetChannelCount(out int count);
    [PreserveSig] int SetMasterVolumeLevel(float level, IntPtr context);
    [PreserveSig] int SetMasterVolumeLevelScalar(float level, IntPtr context);
    [PreserveSig] int GetMasterVolumeLevel(out float level);
    [PreserveSig] int GetMasterVolumeLevelScalar(out float level);
    [PreserveSig] int SetChannelVolumeLevel(int channel, float level, IntPtr context);
    [PreserveSig] int SetChannelVolumeLevelScalar(int channel, float level, IntPtr context);
    [PreserveSig] int GetChannelVolumeLevel(int channel, out float level);
    [PreserveSig] int GetChannelVolumeLevelScalar(int channel, out float level);
    [PreserveSig] int SetMute([MarshalAs(UnmanagedType.Bool)] bool muted, IntPtr context);
    [PreserveSig] int GetMute([MarshalAs(UnmanagedType.Bool)] out bool muted);
  }
  public static class Endpoint {
    public static string MuteAndRead() {
      var enumerator = (IMMDeviceEnumerator)new MMDeviceEnumerator();
      IMMDevice device;
      // The VM's default playback device; WinUAE runs on its console.
      Marshal.ThrowExceptionForHR(enumerator.GetDefaultAudioEndpoint(0, 0, out device));
      string id;
      Marshal.ThrowExceptionForHR(device.GetId(out id));
      Guid iid = typeof(IAudioEndpointVolume).GUID;
      object raw;
      Marshal.ThrowExceptionForHR(device.Activate(ref iid, 23, IntPtr.Zero, out raw));
      var volume = (IAudioEndpointVolume)raw;
      bool before, after;
      Marshal.ThrowExceptionForHR(volume.GetMute(out before));
      Marshal.ThrowExceptionForHR(volume.SetMute(true, IntPtr.Zero));
      Marshal.ThrowExceptionForHR(volume.GetMute(out after));
      return id + "|" + before + "|" + after;
    }
  }
}
'@
try {
  if ($env:COMPUTERNAME -ne 'WIN11-DEV') {
    throw "unexpected Windows VM: $env:COMPUTERNAME"
  }
  Add-Type -TypeDefinition $code -ErrorAction Stop
  $parts = ([WishAudio.Endpoint]::MuteAndRead()).Split('|')
  if ($parts.Count -ne 3 -or [string]::IsNullOrWhiteSpace($parts[0])) {
    throw 'Core Audio returned no playback endpoint ID'
  }
  $before = [bool]::Parse($parts[1])
  $after = [bool]::Parse($parts[2])
  if (-not $after) { throw 'Windows playback endpoint mute readback is false' }
  [pscustomobject]@{
    vm = $env:COMPUTERNAME
    endpoint_id = $parts[0]
    before = $before
    muted = $after
    readback = $true
    observed_utc = [DateTime]::UtcNow.ToString('o')
    method = 'Windows Core Audio endpoint mute readback'
  } | ConvertTo-Json -Compress
} catch {
  Write-Error $_
  exit 1
}
