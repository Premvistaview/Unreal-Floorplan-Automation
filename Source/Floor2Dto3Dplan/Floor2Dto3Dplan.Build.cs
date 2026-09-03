// Copyright Epic Games, Inc. All Rights Reserved.

using UnrealBuildTool;

public class Floor2Dto3Dplan : ModuleRules
{
	public Floor2Dto3Dplan(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[] {
			"Core",
			"CoreUObject",
			"Engine",
			"InputCore",
			"EnhancedInput",
			"AIModule",
			"StateTreeModule",
			"GameplayStateTreeModule",
			"UMG",
			"Slate",
            "GeometryCore", 
			"GeometryFramework"
        });

		PrivateDependencyModuleNames.AddRange(new string[] { });

		if (Target.bBuildEditor)
		{
			PrivateDependencyModuleNames.AddRange(new string[] {
				"DesktopPlatform",
				"SlateCore"
			});
		}

		PublicIncludePaths.AddRange(new string[] {
			"Floor2Dto3Dplan",
			"Floor2Dto3Dplan/Variant_Horror",
			"Floor2Dto3Dplan/Variant_Horror/UI",
			"Floor2Dto3Dplan/Variant_Shooter",
			"Floor2Dto3Dplan/Variant_Shooter/AI",
			"Floor2Dto3Dplan/Variant_Shooter/UI",
			"Floor2Dto3Dplan/Variant_Shooter/Weapons"
		});

		// Uncomment if you are using Slate UI
		// PrivateDependencyModuleNames.AddRange(new string[] { "Slate", "SlateCore" });

		// Uncomment if you are using online features
		// PrivateDependencyModuleNames.Add("OnlineSubsystem");

		// To include OnlineSubsystemSteam, add it to the plugins section in your uproject file with the Enabled attribute set to true
	}
}
